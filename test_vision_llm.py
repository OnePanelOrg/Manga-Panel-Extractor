import json

import cv2 as cv
import numpy as np

from kcore.vision_llm import (
	cache_path,
	cached_request_panels,
	estimate_detector_confidence,
	panel_llm_config,
	parse_panel_message,
	validate_panels,
)
from kumikolib import Kumiko


def test_validate_panels_clamps_tiny_provider_overflow():
	assert validate_panels({
		"panels": [{"x": 0, "y": 0, "w": 100.4, "h": 100.2}]
	}) == [{"x": 0.0, "y": 0.0, "w": 100.0, "h": 100.0}]


def test_panel_llm_config_selects_cheap_model():
	config = panel_llm_config({
		"panel_llm_model": "quality/model",
		"panel_llm_cheap_model": "cheap/model",
		"panel_llm_model_choice": "cheap",
	})

	assert config["model"] == "cheap/model"


def test_parse_panel_message_accepts_pixel_xyxy_lists():
	assert parse_panel_message("[[50, 160, 550, 960]]", (1000, 1600)) == [
		{"x": 5.0, "y": 10.0, "w": 50.0, "h": 50.0}
	]


def test_confidence_flags_single_panel_dense_page():
	gray = np.zeros((200, 200), dtype=np.uint8)
	gray[:, ::8] = 255
	result = {
		"detector": "legacy-contours",
		"backgroundDarkFraction": 0,
		"panels": [{"x": 0, "y": 0, "w": 100, "h": 100}],
	}

	confidence = estimate_detector_confidence(result, gray)

	assert confidence["low"]
	assert "single_or_no_panel" in confidence["reasons"]
	assert "few_panels_on_dense_page" in confidence["reasons"]


def test_cached_request_panels_uses_existing_record(tmp_path, monkeypatch):
	image_path = tmp_path / "page.png"
	cv.imwrite(str(image_path), np.full((20, 20, 3), 255, dtype=np.uint8))
	config = {
		"model": "test/model",
		"cache_dir": tmp_path / "cache",
		"api_key_env": "OPENROUTER_API_KEY",
		"api_url": "https://example.invalid",
		"timeout": 1,
	}
	first = cached_request_panels

	def fail_request(*args, **kwargs):
		raise AssertionError("network should not be called for cache hit")

	monkeypatch.setattr("kcore.vision_llm.request_panels", fail_request)
	cache_file = cache_path(image_path, config["model"], config["cache_dir"])
	config["cache_dir"].mkdir()
	cache_file.write_text(
		json.dumps({"panels": [{"x": 0, "y": 0, "w": 100, "h": 100}]}),
		encoding="utf-8",
	)

	record = first(image_path, config)

	assert record["cache_hit"] is True
	assert record["panels"][0]["w"] == 100


def test_kumiko_always_mode_replaces_local_panels(tmp_path, monkeypatch):
	image_path = tmp_path / "page.png"
	cv.imwrite(str(image_path), np.full((120, 80, 3), 255, dtype=np.uint8))

	def fake_request(filename, config):
		return {
			"panels": [
				{"x": 0, "y": 0, "w": 100, "h": 50},
				{"x": 0, "y": 50, "w": 100, "h": 50},
			],
			"model": "test/model",
			"cache_hit": False,
		}

	monkeypatch.setattr("kumikolib.cached_request_panels", fake_request)

	result = Kumiko({
		"panel_llm_mode": "always",
		"panel_llm_model": "test/model",
	}).parse_image(
		str(image_path),
		{"page.png": {"source_url": "page.png"}},
	)

	assert result["detector"] == "vision-llm"
	assert result["panelLlm"]["localDetector"] == "legacy-contours"
	assert len(result["panels"]) == 2


def test_kumiko_fallback_mode_keeps_high_confidence_local_result(tmp_path, monkeypatch):
	image_path = tmp_path / "page.png"
	image = np.zeros((120, 80, 3), dtype=np.uint8)
	image[10:50, 10:35] = 255
	image[10:50, 45:70] = 255
	image[70:110, 10:70] = 255
	cv.imwrite(str(image_path), image)

	def fail_request(*args, **kwargs):
		raise AssertionError("high-confidence pages should stay local")

	monkeypatch.setattr("kumikolib.cached_request_panels", fail_request)

	result = Kumiko({"panel_llm_mode": "fallback"}).parse_image(
		str(image_path),
		{"page.png": {"source_url": "page.png"}},
	)

	assert result["detector"] in ["adaptive-dark-gutter", "legacy-contours"]
	assert result["detectorConfidence"]["low"] is False
