# Architecture

## Runtime flow

```text
Client
  |
  | POST /v2/chapter
  v
FastAPI (app.py)
  |
  +-- normalize URL and calculate MD5 chapter hash
  |
  +-- utils.download_lmages()
  |     +-- fetch chapter HTML
  |     +-- select matching PNG/WebP <img> sources
  |     `-- write images/<hash>/ and img_dict.json
  |
  +-- Kumiko.parse_dir()
  |     `-- local panel detection, optional vision LLM pass -> kumiko.json
  |
  `-- return result or chapter hash
```

All chapter work happens in the API request process. There is no active queue,
background job, object storage, or shared cache in the checked-in application.

## Components

| Path | Role | Status |
| --- | --- | --- |
| `app.py` | FastAPI application, routing, orchestration, CORS, logging | Active |
| `utils.py` | HTML/image download, file discovery, JSON and image helpers | Active |
| `kumikolib.py`, `kcore/` | Bundled Kumiko page-layout algorithm and optional vision LLM detector | Active |
| `feedback_service.py` | MySQL connection and feedback insert | Active for feedback endpoint |
| `output.json` | Historical example output | Sample only |
| `test_utils.py` | Downloader URL and file-discovery unit tests | Active |

## Data model

For each normalized chapter URL:

```text
images/<md5>/ (temporary during extraction)
  <downloaded pages>
  img_dict.json

jsons/<md5>/
  kumiko.json
```

Downloaded pages use zero-padded sequential filenames and carry a `page_index`
in `img_dict.json`. This preserves source HTML order through extraction. The
whole image directory is removed after extraction, whether processing succeeds
or fails. Legacy results without an explicit index use natural numeric filename
ordering.

The HTTP API stores and returns `kumiko.json`. Older deployments also generated
`panel_extracted.json` using `PanelExtractor`; that duplicate output is no
longer generated, and the legacy extractor has been removed from the repository.

Panel coordinates are percentages of page width and height. The output includes
the source image URL and a list of panel rectangles/paths for every page.

## Algorithm

Kumiko is the default production layout algorithm and is configured for
right-to-left reading:

```python
{
    "debug": False,
    "progress": False,
    "rtl": True,
    "min_panel_size_ratio": False
}
```

`PANEL_LLM_MODE` can enable the vision-LLM detector described in
`docs/VISION_LLM_PANEL_DETECTION_DECISION.md`:

- `off` keeps local detection only. This is the default.
- `fallback` runs local detection first and calls the configured vision LLM only
  when detector-confidence heuristics flag the page as risky.
- `always` uses the configured vision LLM for every page after the local pass.

The production helper asks for strict percentage bounding boxes, validates and
clamps tiny provider overflows, sorts panels in reading order, and caches results
by image hash plus model slug under `.panel_llm_cache/` unless
`PANEL_LLM_CACHE_DIR` overrides it. It records model, latency, usage, request id,
cache status, and confidence reasons in each page's `panelLlm` metadata when the
LLM path is attempted or used. Provider failures fall back to local panels and
store non-secret error metadata.

Model and provider settings:

```text
PANEL_LLM_MODEL_CHOICE=quality|cheap
PANEL_LLM_MODEL=openai/gpt-5.5
PANEL_LLM_CHEAP_MODEL=qwen/qwen3-vl-30b-a3b-thinking
PANEL_LLM_API_URL=https://openrouter.ai/api/v1/chat/completions
PANEL_LLM_API_KEY_ENV=OPENROUTER_API_KEY
PANEL_LLM_TIMEOUT=120
PANEL_LLM_CACHE_DIR=.panel_llm_cache
```

## External dependencies

- Chapter websites and their image CDNs
- OpenRouter or another OpenAI-compatible vision gateway when
  `PANEL_LLM_MODE` is `fallback` or `always`
- MySQL, but only for `POST /v2/feedback`
- OnePanel web clients allowed by the hard-coded CORS list

The old Redis/RQ worker and its disconnected API prototype have been removed.
