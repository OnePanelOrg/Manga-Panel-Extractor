import cv2 as cv
import numpy as np


def border_dark_fraction(gray, threshold=64, border_ratio=0.02):
	"""Return the fraction of near-black pixels in a strip around the page."""
	height, width = gray.shape
	thickness = max(3, int(min(height, width) * border_ratio))
	border = np.concatenate((
		gray[:thickness, :].ravel(),
		gray[-thickness:, :].ravel(),
		gray[:, :thickness].ravel(),
		gray[:, -thickness:].ravel(),
	))
	return float(np.mean(border < threshold))


def has_dark_gutters(gray, minimum_fraction=0.40):
	"""Detect pages whose outer layout is predominantly bounded by black."""
	return border_dark_fraction(gray) >= minimum_fraction


def _runs(mask):
	changes = np.diff(np.concatenate(([False], mask, [False])).astype(np.int8))
	return zip(np.flatnonzero(changes == 1), np.flatnonzero(changes == -1))


def _split_on_dark_gutters(gray, box, depth=0):
	x, y, width, height = box
	if depth >= 12 or width < 100 or height < 120:
		return [box]

	dark = gray[y:y + height, x:x + width] < 128
	candidates = []
	for axis, density, length in (
		('horizontal', dark.mean(axis=1), height),
		('vertical', dark.mean(axis=0), width),
	):
		# A small moving average tolerates compression noise and thin white marks
		# crossing an otherwise solid gutter.
		smoothed = np.convolve(density, np.ones(5) / 5, mode='same')
		for start, end in _runs(smoothed > 0.84):
			thickness = end - start
			edge_distance = min(start, length - end)
			if thickness < max(3, int(length * 0.004)):
				continue
			if edge_distance < max(15, int(length * 0.04)):
				continue
			balance = edge_distance / length
			score = thickness / length * (0.5 + balance)
			candidates.append((score, axis, start, end))

	if not candidates:
		return [box]

	_, axis, start, end = max(candidates)
	if axis == 'horizontal':
		first = (x, y, width, start)
		second = (x, y + end, width, height - end)
	else:
		first = (x, y, start, height)
		second = (x + end, y, width - end, height)

	return (
		_split_on_dark_gutters(gray, first, depth + 1)
		+ _split_on_dark_gutters(gray, second, depth + 1)
	)


def _fit_to_bright_region(gray, box):
	"""Trim a partition to its dominant bright connected region."""
	x, y, width, height = box
	region = (gray[y:y + height, x:x + width] > 25).astype(np.uint8)
	region = cv.morphologyEx(
		region,
		cv.MORPH_CLOSE,
		cv.getStructuringElement(cv.MORPH_RECT, (3, 3)),
	)
	count, _, stats, _ = cv.connectedComponentsWithStats(region, connectivity=8)
	if count <= 1:
		return box

	components = stats[1:]
	# Bounding-box area is intentional: panel line art can make pixel area sparse.
	component = max(components, key=lambda stat: stat[2] * stat[3])
	cx, cy, component_width, component_height, _ = map(int, component)
	return (x + cx, y + cy, component_width, component_height)


def dark_gutter_panels(gray, minimum_panel_ratio):
	"""Partition a black-gutter page and return panel bounding boxes."""
	height, width = gray.shape
	boxes = _split_on_dark_gutters(gray, (0, 0, width, height))
	boxes = [
		_fit_to_bright_region(gray, box)
		for box in boxes
		if box[2] >= width * minimum_panel_ratio
		and box[3] >= height * minimum_panel_ratio
	]
	return boxes
