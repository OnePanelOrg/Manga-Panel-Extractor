# Dark-background panel extraction research

Run the comparison from the repository root:

```sh
PYTHONPATH=. .venv/bin/python research/generate_report.py
```

Then open `research/results/report.html`. The downloaded source fixtures and
generated JPEG overlays are intentionally ignored by Git.

## Findings

The legacy extractor uses fixed grayscale thresholds and accepts the white-page
result whenever it contains more than one region. Panel count is not a useful
quality score, and a dark page is therefore frequently reduced to the fallback
full-page rectangle.

The implemented POC:

1. estimates page polarity from a two-percent strip around the page;
2. selects the dark-gutter path when at least 40 percent of that strip is
   near-black;
3. recursively splits on long, nearly-solid black projection bands;
4. trims each partition to its dominant bright connected region; and
5. retains the legacy contour path for ordinary light pages.

On the local One Piece fixture, pages 11 and 12 improve from one fallback panel
each to visually correct layouts of nine and four panels. Page 13 mixes black
and white gutters: it improves from one region to two, but the lower five panels
remain merged. The report intentionally exposes that failure.

## Why SAM is not the default

SAM and SAM 2 are promptable object segmentation models. A manga panel is a
layout region whose interior contains many visually stronger objects. Automatic
mask generation consequently needs substantial panel-specific selection or
fine-tuning, adds model weights and inference cost, and does not directly solve
reading-order geometry. It remains a possible later benchmark, not the cheapest
or best-aligned first intervention.

## Sources

- Pang et al., *A Robust Panel Extraction Method for Manga*:
  https://ying-cao.com/projects/panel_extraction/files/panel_extraction_paper.pdf
  — background-mask repair followed by recursive binary splitting.
- Stommel et al., *Segmentation-Free Detection of Comic Panels*:
  https://doi.org/10.1007/978-3-642-33564-8_76
  — motivates outline-based detection for structured backgrounds.
- Meta, *SAM 2: Segment Anything in Images and Videos*:
  https://ai.meta.com/research/sam2/
- Manga109 frame annotations:
  https://manga109.github.io/manga109-project-website/en/annotations.html
  — suitable ground truth for a larger detector benchmark.

## Next scientific step

Create a licensed evaluation subset from Manga109 with stratified light, dark,
mixed, borderless, and full-bleed pages. Measure panel-level precision/recall
using one-to-one IoU matching, plus exact page accuracy. The next POC should
combine dark-gutter splits with outline evidence for mixed-polarity leaves,
rather than relaxing projection thresholds globally (which over-segments
speech balloons and white panel interiors).
