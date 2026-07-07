"""Benchmark a vision LLM against Kumiko panel detection.

The gateway APIs are OpenAI-compatible, so this script deliberately uses only
requests rather than adding an SDK dependency.
"""

import argparse
import base64
import json
import os
import re
import time
from io import BytesIO
from pathlib import Path

import cv2 as cv
import requests
from PIL import Image

from kumikolib import Kumiko


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FIXTURES = ROOT / "research" / "fixtures" / "source"
DEFAULT_OUTPUT = ROOT / "research" / "vision-benchmark"
DEFAULT_ENV_FILE = ROOT / ".env"

GATEWAYS = {
	"openrouter": {
		"url": "https://openrouter.ai/api/v1/chat/completions",
		"key": "OPENROUTER_API_KEY",
		"default_model": "openrouter/free",
	},
	"vercel": {
		"url": "https://ai-gateway.vercel.sh/v1/chat/completions",
		"key": "AI_GATEWAY_API_KEY",
		"default_model": "google/gemini-3-flash",
	},
}

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


class VisionBenchmarkError(RuntimeError):
	def __init__(self, message, debug=None):
		super().__init__(message)
		self.debug = debug or {}


def load_env_file(path):
	"""Load KEY=VALUE pairs from a local .env file without overriding env vars."""
	if not path or not path.exists():
		return []
	loaded = []
	for raw_line in path.read_text(encoding="utf-8").splitlines():
		line = raw_line.strip()
		if not line or line.startswith("#"):
			continue
		if line.startswith("export "):
			line = line[len("export "):].strip()
		if "=" not in line:
			continue
		key, value = line.split("=", 1)
		key = key.strip()
		value = value.strip()
		if not key or key in os.environ:
			continue
		if (
			len(value) >= 2
			and value[0] == value[-1]
			and value[0] in ("'", '"')
		):
			value = value[1:-1]
		os.environ[key] = value
		loaded.append(key)
	return loaded


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
		if (
			x < 0 or y < 0 or width <= 0 or height <= 0
			or x + width > 100.5 or y + height > 100.5
		):
			raise ValueError(f"panel lies outside the image: {panel}")
		normalized.append({"x": x, "y": y, "w": width, "h": height})
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


def request_panels(path, gateway, model, timeout):
	config = GATEWAYS[gateway]
	api_key = os.getenv(config["key"])
	if not api_key:
		raise RuntimeError(f"set {config['key']} before running the benchmark")
	body = {
		"model": model,
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
		config["url"],
		headers={
			"Authorization": f"Bearer {api_key}",
			"Content-Type": "application/json",
		},
		json=body,
		timeout=timeout,
	)
	elapsed = time.monotonic() - started
	response.raise_for_status()
	debug = {
		"latency_seconds": round(elapsed, 3),
		"http_status": response.status_code,
		"response_text": response.text[:4000],
	}
	try:
		raw = response.json()
	except ValueError as error:
		raise VisionBenchmarkError("provider response is not JSON", debug) from error
	debug.update({
		"model": raw.get("model", model) if isinstance(raw, dict) else model,
		"usage": raw.get("usage") if isinstance(raw, dict) else None,
		"request_id": raw.get("id") if isinstance(raw, dict) else None,
		"provider_error": raw.get("error") if isinstance(raw, dict) else None,
	})
	try:
		message = raw["choices"][0]["message"]["content"]
	except (KeyError, IndexError, TypeError) as error:
		raise VisionBenchmarkError("provider response does not contain choices", debug) from error
	if isinstance(message, list):
		message = "".join(part.get("text", "") for part in message)
	debug["message"] = message[:4000] if isinstance(message, str) else repr(message)
	try:
		with Image.open(path) as image:
			panels = parse_panel_message(message, image.size)
	except ValueError as error:
		raise VisionBenchmarkError(str(error), debug) from error
	return {
		"panels": panels,
		"latency_seconds": round(elapsed, 3),
		"model": raw.get("model", model),
		"usage": raw.get("usage"),
		"request_id": raw.get("id"),
	}


def baseline_panels(path):
	result = Kumiko({"rtl": True, "dark_page_strategy": "adaptive"}).parse_image(
		str(path), {path.name: {"source_url": path.name}}
	)
	return {
		"panels": [
			{key: panel[key] for key in ("x", "y", "w", "h")}
			for panel in result["panels"]
		],
		"detector": result["detector"],
	}


def draw_overlay(source, panels, destination, colour):
	image = cv.imread(str(source))
	height, width = image.shape[:2]
	for index, panel in enumerate(panels, start=1):
		x = round(panel["x"] * width / 100)
		y = round(panel["y"] * height / 100)
		right = round((panel["x"] + panel["w"]) * width / 100)
		bottom = round((panel["y"] + panel["h"]) * height / 100)
		cv.rectangle(image, (x, y), (right, bottom), colour, max(3, width // 250))
		cv.putText(
			image, str(index), (x + 8, y + 32), cv.FONT_HERSHEY_SIMPLEX,
			1, colour, 3,
		)
	cv.imwrite(str(destination), image)


def main():
	parser = argparse.ArgumentParser()
	parser.add_argument("--provider", choices=GATEWAYS, default="vercel")
	parser.add_argument("--model", help="gateway model slug")
	parser.add_argument("--fixtures", type=Path, default=DEFAULT_FIXTURES)
	parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
	parser.add_argument("--limit", type=int)
	parser.add_argument("--timeout", type=int, default=120)
	parser.add_argument("--overwrite", action="store_true")
	parser.add_argument(
		"--env-file", type=Path, default=DEFAULT_ENV_FILE,
		help="local .env file to load before calling providers",
	)
	args = parser.parse_args()
	load_env_file(args.env_file)
	model = args.model or GATEWAYS[args.provider]["default_model"]
	paths = sorted(args.fixtures.glob("*.png"))
	if args.limit:
		paths = paths[:args.limit]
	if not paths:
		raise SystemExit(f"no PNG fixtures found in {args.fixtures}")

	args.output.mkdir(parents=True, exist_ok=True)
	for path in paths:
		result_path = args.output / f"{path.stem}.json"
		if result_path.exists() and not args.overwrite:
			print(f"skip {path.name}: {result_path.name} exists")
			continue
		print(f"benchmark {path.name} with {model}", flush=True)
		record = {
			"image": path.name,
			"provider": args.provider,
			"requested_model": model,
			"baseline": baseline_panels(path),
		}
		try:
			record["llm"] = request_panels(path, args.provider, model, args.timeout)
		except VisionBenchmarkError as error:
			record["error"] = f"{type(error).__name__}: {error}"
			record["llm_debug"] = error.debug
		except Exception as error:
			record["error"] = f"{type(error).__name__}: {error}"
		result_path.write_text(json.dumps(record, indent=2), encoding="utf-8")
		if "llm" in record:
			draw_overlay(
				path, record["baseline"]["panels"],
				args.output / f"{path.stem}-baseline.jpg", (0, 40, 255),
			)
			draw_overlay(
				path, record["llm"]["panels"],
				args.output / f"{path.stem}-llm.jpg", (30, 220, 30),
			)
	print(f"results: {args.output}")


if __name__ == "__main__":
	main()
