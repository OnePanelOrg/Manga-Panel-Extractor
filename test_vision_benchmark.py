import os

import pytest

from research.benchmark_vision import load_env_file, parse_panel_message, validate_panels


def test_validate_panels_normalizes_numbers():
	assert validate_panels({
		"panels": [{"x": 1, "y": "2", "w": 30, "h": 40}]
	}) == [{"x": 1.0, "y": 2.0, "w": 30.0, "h": 40.0}]


@pytest.mark.parametrize("panel", [
	{"x": -1, "y": 0, "w": 10, "h": 10},
	{"x": 95, "y": 0, "w": 10, "h": 10},
	{"x": 0, "y": 0, "w": 0, "h": 10},
])
def test_validate_panels_rejects_invalid_boxes(panel):
	with pytest.raises(ValueError):
		validate_panels({"panels": [panel]})


def test_parse_panel_message_accepts_coordinate_tuple_string():
	assert parse_panel_message(
		"(0, 0, 100, 44), (0, 44, 50, 22)", (1000, 1600)
	) == [
		{"x": 0.0, "y": 0.0, "w": 100.0, "h": 44.0},
		{"x": 0.0, "y": 44.0, "w": 50.0, "h": 22.0},
	]


def test_parse_panel_message_accepts_pixel_xyxy_lists():
	assert parse_panel_message("[[50, 160, 550, 960]]", (1000, 1600)) == [
		{"x": 5.0, "y": 10.0, "w": 50.0, "h": 50.0}
	]


def test_load_env_file_sets_missing_values(tmp_path, monkeypatch):
	monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
	env_path = tmp_path / ".env"
	env_path.write_text("OPENROUTER_API_KEY=secret-test-key\n", encoding="utf-8")

	assert load_env_file(env_path) == ["OPENROUTER_API_KEY"]
	assert "secret-test-key" == os.environ["OPENROUTER_API_KEY"]


def test_load_env_file_does_not_override_existing_values(tmp_path, monkeypatch):
	monkeypatch.setenv("OPENROUTER_API_KEY", "existing-key")
	env_path = tmp_path / ".env"
	env_path.write_text("OPENROUTER_API_KEY=file-key\n", encoding="utf-8")

	assert load_env_file(env_path) == []
	assert "existing-key" == os.environ["OPENROUTER_API_KEY"]


def test_load_env_file_accepts_export_and_quotes(tmp_path, monkeypatch):
	monkeypatch.delenv("AI_GATEWAY_API_KEY", raising=False)
	env_path = tmp_path / ".env"
	env_path.write_text(
		"# local secrets\nexport AI_GATEWAY_API_KEY='quoted-key'\n",
		encoding="utf-8",
	)

	assert load_env_file(env_path) == ["AI_GATEWAY_API_KEY"]
	assert "quoted-key" == os.environ["AI_GATEWAY_API_KEY"]
