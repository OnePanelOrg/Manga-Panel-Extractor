import cv2 as cv
import numpy as np

from kcore.detection import (
	border_dark_fraction,
	dark_gutter_panels,
	has_dark_gutters,
)


def make_grid(background, panels):
	image = np.full((600, 400), background, dtype=np.uint8)
	for x, y, width, height in panels:
		image[y:y + height, x:x + width] = 245
		cv.rectangle(
			image,
			(x + 20, y + 20),
			(x + width - 20, y + height - 20),
			80,
			2,
		)
	return image


def test_border_dark_fraction_distinguishes_page_polarity():
	dark_page = make_grid(0, [(20, 20, 360, 260), (20, 320, 360, 260)])
	light_page = np.full((600, 400), 255, dtype=np.uint8)

	assert border_dark_fraction(dark_page) > 0.90
	assert has_dark_gutters(dark_page)
	assert border_dark_fraction(light_page) == 0
	assert not has_dark_gutters(light_page)


def test_dark_gutter_detector_recovers_regular_grid():
	expected = [
		(20, 20, 170, 260),
		(210, 20, 170, 260),
		(20, 320, 170, 260),
		(210, 320, 170, 260),
	]
	image = make_grid(0, expected)

	assert dark_gutter_panels(image, minimum_panel_ratio=1 / 15) == expected


def test_dark_gutter_detector_handles_nested_layout():
	expected = [
		(20, 20, 360, 180),
		(20, 240, 170, 340),
		(210, 240, 170, 340),
	]
	image = make_grid(0, expected)

	assert dark_gutter_panels(image, minimum_panel_ratio=1 / 15) == expected
