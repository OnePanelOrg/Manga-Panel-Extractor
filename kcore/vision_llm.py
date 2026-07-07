import base64
import hashlib
import json
import os
import re
import time
from io import BytesIO
from pathlib import Path

import requests
import numpy as np
from PIL import Image


OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_QUALITY_MODEL = "openai/gpt-5.5"
DEFAULT_CHEAP_MODEL = "qwen/qwen3-vl-30b-a3b-thinking"

PANEL_SCHEMA = {
	"type": "object",
	"additionalProperties": False,
	"properties": {
		"panels": {
			"type": "array",
			"items": {
				"type": "object",
				"additionalProperties": False,
				"properties": {
					"x": {"type": "number", "minimum": 0, "maximum": 100},
					"y": {"type": "number", "minimum": 0, "maximum": 100},
					"w": {"type": "number", "exclusiveMinimum": 0, "maximum": 100},
					"h": {"type": "number", "exclusiveMinimum": 0, "maximum": 100},
				},
				"required": ["x", "y", "w", "h"],
			},
		},
	},
	"required": ["panels"],
}

PROMPT = """Find every manga/comic story panel in this page.
Return each panel's tight axis-aligned bounding box as percentages of the full
image: x and y are the top-left corner, w and h are width and height.
Include borderless and full-bleed panels. Exclude speech balloons, captions,
characters, inset decorations, and the whole page unless it is genuinely one
panel. Do not merge panels separated by a gutter or border."""


class VisionPanelError(RuntimeError):
	def __init__(self, message, debug=None):
		super().__init__(message)
		self.debug = debug or {}


def panel_llm_config(options=None):
	options = options or {}
	quality_model = options.get("panel_llm_model") or os.getenv(
		"PANEL_LLM_MODEL", DEFAULT_QUALITY_MODEL,
	)
	cheap_model = options.get("panel_llm_cheap_model") or os.getenv(
		"PANEL_LLM_CHEAP_MODEL", DEFAULT_CHEAP_MODEL,
	)
	model_choice = (
		options.get("panel_llm_model_choice")
		or os.getenv("PANEL_LLM_MODEL_CHOICE", "quality")
	).lower()
	model = cheap_model if model_choice == "cheap" else quality_model
	return {
		"mode": (
			options.get("panel_llm_mode")
			or os.getenv("PANEL_LLM_MODE", "off")
		).lower(),
		"model": model,
		"quality_model": quality_model,
		"cheap_model": cheap_model,
		"model_choice": model_choice,
		"api_url": options.get("panel_llm_api_url") or os.getenv(
			"PANEL_LLM_API_URL", OPENROUTER_URL,
		),
		"api_key_env": options.get("panel_llm_api_key_env") or os.getenv(
			"PANEL_LLM_API_KEY_ENV", "OPENROUTER_API_KEY",
		),
		"timeout": int(options.get("panel_llm_timeout") or os.getenv(
			"PANEL_LLM_TIMEOUT", "120",
		)),
		"cache_dir": Path(options.get("panel_llm_cache_dir") or os.getenv(
			"PANEL_LLM_CACHE_DIR", ".panel_llm_cache",
		)),
	}


def image_sha256(path):
	digest = hashlib.sha256()
	with open(path, "rb") as handle:
		for chunk in iter(lambda: handle.read(1024 * 1024), b""):
			digest.update(chunk)
	return digest.hexdigest()


def cache_path(path, model, cache_dir):
	safe_model = re.sub(r"[^A-Za-z0-9_.-]+", "_", model)
	return cache_dir / f"{image_sha256(path)}-{safe_model}.json"


def image_data_url(path, max_dimension=1600):
	with Image.open(path) as image:
		image = image.convert("RGB")
		image.thumbnail((max_dimension, max_dimension))
		buffer = BytesIO()
		image.save(buffer, format="JPEG", quality=90)
	return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode()


def validate_panels(payload):
	panels = payload.get("panels") if isinstance(payload, dict) else None
	if not isinstance(panels, list):
		raise ValueError("response does not contain a panels array")
	normalized = []
	for panel in panels:
		if not isinstance(panel, dict):
			raise ValueError("panel is not an object")
		try:
			x, y, width, height = (
				float(panel[name]) for name in ("x", "y", "w", "h")
			)
		except (KeyError, TypeError, ValueError) as error:
			raise ValueError("panel has invalid coordinates") from error
		if x < 0 or y < 0 or x > 100 or y > 100 or width <= 0 or height <= 0:
			raise ValueError(f"panel lies outside the image: {panel}")
		if x + width > 100.5 or y + height > 100.5:
			raise ValueError(f"panel lies outside the image: {panel}")
		normalized.append({
			"x": max(0.0, min(100.0, x)),
			"y": max(0.0, min(100.0, y)),
			"w": max(0.0, min(100.0 - x, width)),
			"h": max(0.0, min(100.0 - y, height)),
		})
	return normalized


def normalize_coordinate_list(items, image_size):
	width, height = image_size
	normalized = []
	for item in items:
		if not isinstance(item, (list, tuple)) or len(item) != 4:
			raise ValueError("panel coordinate list must contain four numbers")
		try:
			a, b, c, d = (float(value) for value in item)
		except (TypeError, ValueError) as error:
			raise ValueError("panel coordinate list has invalid numbers") from error
		if max(a, b, c, d) <= 100.5:
			normalized.append({"x": a, "y": b, "w": c, "h": d})
		elif c > a and d > b and c <= width * 1.05 and d <= height * 1.05:
			normalized.append({
				"x": a * 100 / width,
				"y": b * 100 / height,
				"w": (c - a) * 100 / width,
				"h": (d - b) * 100 / height,
			})
		else:
			normalized.append({
				"x": a * 100 / width,
				"y": b * 100 / height,
				"w": c * 100 / width,
				"h": d * 100 / height,
			})
	return validate_panels({"panels": normalized})


def parse_panel_message(message, image_size):
	try:
		payload = json.loads(message)
	except (TypeError, json.JSONDecodeError):
		payload = None
	if isinstance(payload, dict):
		return validate_panels(payload)
	if isinstance(payload, list):
		return normalize_coordinate_list(payload, image_size)
	numbers = [
		float(match) for match in
		re.findall(r"-?\d+(?:\.\d+)?", message if isinstance(message, str) else "")
	]
	if numbers and len(numbers) % 4 == 0:
		return normalize_coordinate_list(
			[numbers[index:index + 4] for index in range(0, len(numbers), 4)],
			image_size,
		)
	raise ValueError("model response is not valid panel JSON or coordinate list")


def request_panels(path, config):
	api_key = os.getenv(config["api_key_env"])
	if not api_key:
		raise VisionPanelError(f"set {config['api_key_env']} before using panel LLM")
	body = {
		"model": config["model"],
		"temperature": 0,
		"messages": [{
			"role": "user",
			"content": [
				{"type": "text", "text": PROMPT},
				{"type": "image_url", "image_url": {"url": image_data_url(path)}},
			],
		}],
		"response_format": {
			"type": "json_schema",
			"json_schema": {
				"name": "manga_panels",
				"strict": True,
				"schema": PANEL_SCHEMA,
			},
		},
	}
	started = time.monotonic()
	response = requests.post(
		config["api_url"],
		headers={
			"Authorization": f"Bearer {api_key}",
			"Content-Type": "application/json",
		},
		json=body,
		timeout=config["timeout"],
	)
	elapsed = time.monotonic() - started
	debug = {
		"latency_seconds": round(elapsed, 3),
		"http_status": response.status_code,
		"response_text": response.text[:4000],
	}
	try:
		response.raise_for_status()
	except requests.HTTPError as error:
		raise VisionPanelError("provider request failed", debug) from error
	try:
		raw = response.json()
	except ValueError as error:
		raise VisionPanelError("provider response is not JSON", debug) from error
	debug.update({
		"model": raw.get("model", config["model"]) if isinstance(raw, dict) else config["model"],
		"usage": raw.get("usage") if isinstance(raw, dict) else None,
		"request_id": raw.get("id") if isinstance(raw, dict) else None,
		"provider_error": raw.get("error") if isinstance(raw, dict) else None,
	})
	try:
		message = raw["choices"][0]["message"]["content"]
	except (KeyError, IndexError, TypeError) as error:
		raise VisionPanelError("provider response does not contain choices", debug) from error
	if isinstance(message, list):
		message = "".join(part.get("text", "") for part in message)
	debug["message"] = message[:4000] if isinstance(message, str) else repr(message)
	try:
		with Image.open(path) as image:
			panels = parse_panel_message(message, image.size)
	except ValueError as error:
		raise VisionPanelError(str(error), debug) from error
	return {
		"panels": panels,
		"latency_seconds": round(elapsed, 3),
		"model": raw.get("model", config["model"]),
		"usage": raw.get("usage"),
		"request_id": raw.get("id"),
		"cache_hit": False,
	}


def cached_request_panels(path, config):
	result_path = cache_path(path, config["model"], config["cache_dir"])
	if result_path.exists():
		with result_path.open(encoding="utf-8") as handle:
			record = json.load(handle)
		record["cache_hit"] = True
		return record
	record = request_panels(path, config)
	config["cache_dir"].mkdir(parents=True, exist_ok=True)
	with result_path.open("w", encoding="utf-8") as handle:
		json.dump(record, handle, indent=2)
	return record


def panels_overlap_fraction(first, second):
	left = max(first["x"], second["x"])
	top = max(first["y"], second["y"])
	right = min(first["x"] + first["w"], second["x"] + second["w"])
	bottom = min(first["y"] + first["h"], second["y"] + second["h"])
	if right <= left or bottom <= top:
		return 0.0
	intersection = (right - left) * (bottom - top)
	smaller = min(first["w"] * first["h"], second["w"] * second["h"])
	return intersection / smaller if smaller else 0.0


def estimate_detector_confidence(result, gray):
	panels = [
		{key: float(panel[key]) for key in ("x", "y", "w", "h")}
		for panel in result.get("panels", [])
	]
	reasons = []
	if len(panels) <= 1:
		reasons.append("single_or_no_panel")
	if len(panels) < 3 and edge_density(gray) > 0.08:
		reasons.append("few_panels_on_dense_page")
	if panels and max(panel["w"] * panel["h"] for panel in panels) > 6800:
		if len(panels) > 1 or edge_density(gray) > 0.08:
			reasons.append("huge_panel_on_complex_page")
	if result.get("detector") == "adaptive-dark-gutter" and len(panels) < 3:
		reasons.append("adaptive_dark_gutter_few_panels")
	for index, panel in enumerate(panels):
		for other in panels[index + 1:]:
			if panels_overlap_fraction(panel, other) > 0.25:
				reasons.append("heavy_panel_overlap")
				break
		if "heavy_panel_overlap" in reasons:
			break
	dark_fraction = result.get("backgroundDarkFraction")
	if isinstance(dark_fraction, (int, float)) and 0.15 < dark_fraction < 0.75:
		reasons.append("mixed_page_border_polarity")
	return {
		"low": bool(reasons),
		"reasons": reasons,
	}


def edge_density(gray):
	edges = Image.fromarray(gray).convert("L")
	# Avoid adding another OpenCV dependency here; gray already came from OpenCV.
	array = np.array(edges)
	height, width = array.shape
	if height < 2 or width < 2:
		return 0.0
	dx = abs(array[:, 1:].astype("int16") - array[:, :-1].astype("int16"))
	dy = abs(array[1:, :].astype("int16") - array[:-1, :].astype("int16"))
	return float(((dx > 40).mean() + (dy > 40).mean()) / 2)
