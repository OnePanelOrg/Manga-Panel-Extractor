"""Generate a self-contained visual comparison of panel detector strategies."""

import html
from pathlib import Path

import cv2 as cv

from kumikolib import Kumiko


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / 'research' / 'fixtures' / 'source'
RESULTS = ROOT / 'research' / 'results'


def extract(path, strategy):
	kumiko = Kumiko({'rtl': True, 'dark_page_strategy': strategy})
	return kumiko.parse_image(
		str(path),
		{path.name: {'source_url': path.name}},
	)


def overlay(source, result, destination):
	image = cv.imread(str(source))
	height, width = image.shape[:2]
	for index, panel in enumerate(result['panels'], start=1):
		x = round(panel['x'] * width / 100)
		y = round(panel['y'] * height / 100)
		panel_width = round(panel['w'] * width / 100)
		panel_height = round(panel['h'] * height / 100)
		cv.rectangle(
			image,
			(x, y),
			(x + panel_width, y + panel_height),
			(0, 40, 255),
			max(3, width // 250),
		)
		cv.putText(
			image,
			str(index),
			(x + 8, y + 32),
			cv.FONT_HERSHEY_SIMPLEX,
			1,
			(255, 80, 0),
			3,
		)
	cv.imwrite(str(destination), image)


def main():
	RESULTS.mkdir(parents=True, exist_ok=True)
	rows = []
	for source in sorted(FIXTURES.glob('*.png')):
		legacy = extract(source, 'legacy')
		adaptive = extract(source, 'adaptive')
		legacy_name = f'{source.stem}-legacy.jpg'
		adaptive_name = f'{source.stem}-adaptive.jpg'
		overlay(source, legacy, RESULTS / legacy_name)
		overlay(source, adaptive, RESULTS / adaptive_name)
		rows.append({
			'name': source.name,
			'dark_fraction': adaptive['backgroundDarkFraction'],
			'legacy': legacy,
			'adaptive': adaptive,
			'legacy_image': legacy_name,
			'adaptive_image': adaptive_name,
		})

	sections = []
	for row in rows:
		changed = len(row['legacy']['panels']) != len(row['adaptive']['panels'])
		sections.append(f"""
		<section class="{'changed' if changed else ''}">
			<h2>{html.escape(row['name'])}</h2>
			<p>Border dark fraction: {row['dark_fraction']:.3f}.
			Legacy: {len(row['legacy']['panels'])} panel(s).
			Adaptive: {len(row['adaptive']['panels'])} panel(s),
			{html.escape(row['adaptive']['detector'])}.</p>
			<div class="comparison">
				<figure><img src="{row['legacy_image']}"><figcaption>Legacy contours</figcaption></figure>
				<figure><img src="{row['adaptive_image']}"><figcaption>Adaptive strategy</figcaption></figure>
			</div>
		</section>""")

	report = f"""<!doctype html>
	<html lang="en"><head><meta charset="utf-8">
	<meta name="viewport" content="width=device-width, initial-scale=1">
	<title>Manga panel detector comparison</title>
	<style>
	body {{ background:#15171a; color:#e8e8e8; font:16px system-ui; margin:2rem auto; max-width:1500px; padding:0 1rem; }}
	h1 {{ margin-bottom:.25rem; }} .summary {{ color:#b9c0c8; }}
	section {{ border-top:1px solid #3a3f45; margin-top:2rem; padding-top:1rem; }}
	section.changed h2::after {{ content:" changed"; color:#70d6a1; font-size:.65em; }}
	.comparison {{ display:grid; grid-template-columns:1fr 1fr; gap:1rem; align-items:start; }}
	figure {{ margin:0; }} img {{ background:white; display:block; max-height:80vh; max-width:100%; margin:auto; }}
	figcaption {{ text-align:center; padding:.5rem; color:#b9c0c8; }}
	@media(max-width:800px) {{ .comparison {{ grid-template-columns:1fr; }} }}
	</style></head><body>
	<h1>Manga panel detector comparison</h1>
	<p class="summary">Red boxes are extracted panels. Changed pages are marked in green.
	The border-dark statistic selects the adaptive black-gutter path at 0.40 or above.</p>
	{''.join(sections)}
	</body></html>"""
	(RESULTS / 'report.html').write_text(report, encoding='utf-8')
	print(RESULTS / 'report.html')


if __name__ == '__main__':
	main()
