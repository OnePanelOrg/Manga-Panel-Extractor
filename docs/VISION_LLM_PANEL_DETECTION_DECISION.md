# Vision LLM panel-detection decision

Date: 2026-07-07

## Decision

Use a vision LLM as a paid panel-detection fallback, and allow GPT-5.5 to be
used either as the low-confidence fallback or as the complete panel detector for
paid product flows where quality matters more than inference cost.

Recommended implementation path:

1. Run the current local detector first.
2. Estimate detector confidence from layout heuristics.
3. If confidence is low, call a vision LLM.
4. Use `openai/gpt-5.5` as the highest-quality fallback.
5. Keep `qwen/qwen3-vl-30b-a3b-thinking` available as the cheaper
   price/quality candidate if cost becomes a concern.

For paid product usage, it is acceptable to spend more on GPT-5.5 when it avoids
bad panel extraction results. The fallback should be designed so we can switch
between "local-first with GPT fallback" and "GPT does the complete thing" with a
configuration flag.

## Why

The current detector is fast and free, but it fails on mixed-polarity,
borderless, full-bleed, and visually complex manga pages. A vision LLM was much
better at understanding page topology on the hard examples.

The best observed quality was from `openai/gpt-5.5`. It found substantially
better layouts on the known hard page `onepiece_1073_miss_013.png`, where the
local detector collapsed most of the lower page.

Because this is now intended for a paid product, quality and user trust matter
more than minimizing every fraction of a cent. GPT-5.5 should therefore be
treated as a valid production option, not only as a research ceiling.

## Benchmark summary

Benchmark fixture set: `research/fixtures/source/onepiece_1073_miss_001.png`
through `onepiece_1073_miss_016.png`.

OpenRouter model bake-off results:

| Model | Usable pages | Total cost | Avg/page | Avg latency | Hard page 13 |
|---|---:|---:|---:|---:|---|
| `google/gemini-2.5-flash-lite` | 10/16 | ~$0.003 | ~$0.0003 | ~3.3s | 4 panels |
| `qwen/qwen3-vl-30b-a3b-thinking` | 16/16 | ~$0.081 | ~$0.0051 | ~28.6s | 6 panels |
| `z-ai/glm-4.6v` | 11/16 | ~$0.024 | ~$0.0021 | ~43.1s | failed |
| `openai/gpt-5.5` | 16/16 | ~$1.219 | ~$0.0762 | ~60.8s | 8 panels |

Interpretation:

- GPT-5.5 was the best visual result and the best choice when quality is the
  priority.
- Qwen was the best cheaper controlled candidate.
- GLM was cheaper than Qwen, but failed too often and failed on the important
  hard page.
- Gemini was extremely cheap, but not reliable enough for production panel
  detection.

Generated comparison artifacts from the research run:

- `research/vision-benchmark-page013-comparison.jpg`
- `research/vision-benchmark-model-bakeoff-contact-sheet.jpg`
- `research/vision-benchmark-gpt55/`
- `research/vision-benchmark-qwen3-vl-30b-thinking/`
- `research/vision-benchmark-glm46v-rerun/`
- `research/vision-benchmark-gemini25-flash-lite/`

These generated artifacts are ignored by Git.

## Suggested production architecture

```text
input page
  -> local detector
  -> confidence check
      -> high confidence: use local boxes
      -> low confidence: call vision LLM
          -> preferred quality mode: openai/gpt-5.5
          -> cheaper mode: qwen/qwen3-vl-30b-a3b-thinking
  -> normalize boxes
  -> validate/clamp/reject invalid boxes
  -> reading-order sort
  -> crop/export panels
```

## Confidence heuristics to start with

Flag low confidence when any of these are true:

- detector returns one panel for a page that is not obviously a cover/splash;
- detector returns very few panels on a dense manga page;
- huge panel covers most of the page while visible gutters remain;
- dark-page adaptive detector returns merged lower rows;
- bounding boxes overlap heavily or leave suspicious large unassigned regions;
- page has mixed black and white gutters;
- panel count or geometry differs sharply between legacy and adaptive detector
  modes.

These are deliberately heuristic. They are enough for a first implementation;
later we should replace them with measured confidence from annotated fixtures.

## LLM response contract

Ask the model for panel bounding boxes as percentages of the full image:

```json
{
  "panels": [
    {"x": 0, "y": 0, "w": 100, "h": 30}
  ]
}
```

Coordinates:

- `x`, `y`: top-left corner in percent.
- `w`, `h`: width and height in percent.
- Include borderless and full-bleed panels.
- Exclude speech balloons, captions, characters, decorative insets, and the
  whole page unless it is genuinely one panel.
- Do not merge panels separated by a gutter or border.

The benchmark harness already includes tolerant parsing for models that return
raw coordinate lists, but production should prefer strict JSON and validation.

## Implementation notes for the next thread

- The benchmark script is `research/benchmark_vision.py`.
- It loads provider keys from repo-root `.env`.
- `OPENROUTER_API_KEY` is the key expected for OpenRouter.
- `.env` is ignored by Git and should remain local.
- Do not log API keys or full request headers.
- Store model, latency, usage, request id, and validation errors for debugging.
- Use a config flag for model selection, e.g.:
  - `PANEL_LLM_MODE=off|fallback|always`
  - `PANEL_LLM_MODEL=openai/gpt-5.5`
  - `PANEL_LLM_CHEAP_MODEL=qwen/qwen3-vl-30b-a3b-thinking`
- Add a budget guard before enabling "always" mode broadly.
- Cache LLM results by image hash and model slug to avoid paying twice for the
  same page.

## Open question

Whether GPT-5.5 should be the default for every paid extraction or only for
low-confidence pages depends on final unit economics. The quality result
supports both options; the first implementation should make this a runtime
configuration choice.
