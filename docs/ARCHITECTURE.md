# Architecture

## Runtime flow

```text
Client
  |
  | POST /chapter or /v2/chapter
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
  |     `-- reading layout -> kumiko.json
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
| `kumikolib.py`, `kcore/` | Bundled Kumiko page-layout algorithm | Active |
| `feedback_service.py` | MySQL connection and feedback insert | Active for feedback endpoint |
| `output.json` | Historical example output | Sample only |
| `test_utils.py` | Downloader URL and file-discovery unit tests | Active |

## Data model

For each normalized chapter URL:

```text
images/<md5>/
  <downloaded pages>
  img_dict.json

jsons/<md5>/
  kumiko.json
```

The HTTP API stores and returns `kumiko.json`. Older deployments also generated
`panel_extracted.json` using `PanelExtractor`; that duplicate output is no
longer generated, and the legacy extractor has been removed from the repository.

Panel coordinates are percentages of page width and height. The output includes
the source image URL and a list of panel rectangles/paths for every page.

## Algorithm

Kumiko is the single production layout algorithm and is configured for
right-to-left reading:

```python
{
    "debug": False,
    "progress": False,
    "rtl": True,
    "min_panel_size_ratio": False
}
```

## External dependencies

- Chapter websites and their image CDNs
- MySQL, but only for `POST /v2/feedback`
- OnePanel web clients allowed by the hard-coded CORS list

The old Redis/RQ worker and its disconnected API prototype have been removed.
