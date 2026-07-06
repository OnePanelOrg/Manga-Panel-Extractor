# Manga Panel Extractor

Python service used by OnePanel to download the pages of a manga chapter, detect
panel geometry, and return reader-layout JSON.

This repository is the backend currently understood to be deployed on Railway.
The deployment and billing facts supplied by the project owner are recorded in
[`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md). The repository itself does not
contain a Railway configuration file, so dashboard-only settings still need to
be verified there.

## What it does

Given a chapter URL, the service:

1. downloads matching PNG images from the chapter HTML;
2. stores the original image URLs alongside the temporary downloads;
3. calculates the panel layout using the bundled Kumiko implementation;
4. caches the result under `jsons/<chapter_hash>/kumiko.json`; and
5. deletes the temporary images and returns the Kumiko result to the caller.

The chapter hash is the MD5 of the chapter URL after its query string is
removed. Processing and caching are synchronous and local to the service
instance.

## API

Run locally:

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app:app --reload --host 0.0.0.0 --port 8000
```

Interactive API documentation is available at
`http://localhost:8000/docs`.

### Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/` | Basic process check; returns `{"Hello":"World"}` |
| `POST` | `/v2/chapter` | Process a chapter and return its hash |
| `GET` | `/v2/chapter/{chapter_hash}` | Read a cached Kumiko result |
| `GET` | `/v2/billing/status` | Read the authenticated user's subscription |
| `POST` | `/v2/billing/checkout` | Create a Stripe subscription Checkout |
| `POST` | `/v2/billing/portal` | Open Stripe's customer billing portal |
| `POST` | `/v2/feedback` | Save feedback to the configured MySQL database |

Request body for the chapter POST:

```json
{
  "chapter_url": "https://example.com/chapter/123"
}
```

Feedback body:

```json
{
  "chapter_hash": "md5-hash",
  "rating": 5,
  "comment": "Optional reader feedback"
}
```

Chapter and billing endpoints require a Clerk bearer token. Chapter creation and
retrieval also require an active Stripe subscription. Configure:

```text
CLERK_ISSUER
CLERK_JWKS_URL
CLERK_AUTHORIZED_PARTIES=http://localhost:3000,https://reader.onepanel.app
STRIPE_SECRET_KEY
STRIPE_PRICE_ID
FRONTEND_URL=https://reader.onepanel.app
```

`STRIPE_PRICE_ID` must reference an active recurring Price for exactly €4.99 EUR
per month. Checkout does not configure a free trial. Subscription access is
checked directly against Stripe, making Stripe the source of truth.

`POST /v2/feedback` requires database variables:

```text
DATABASE_HOST
DATABASE_NAME
DATABASE_USER
DATABASE_PASSWORD
```

Railway MySQL reference-variable mappings and the required `feedback` table
schema are documented in [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

Do not commit `.env`; it is ignored by Git.

## Current source compatibility

The downloader accepts `.png` and `.webp` image `src` values whose absolute URL
begins with `https://i`. URL query strings and uppercase extensions are
supported. Sites using lazy-loading attributes, relative URLs, different host
patterns, or other image formats still require an adapter.

An extraction that finds zero usable pages returns HTTP 422 and is not cached.

The API is the supported entry point. The older OpenCV `PanelExtractor`, CLI,
Redis worker experiment, hard-coded downloader, and PID-based process scripts
have been removed. The API generates only `kumiko.json`.

## Documentation

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — components, data flow, and
  repository map
- [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) — Railway deployment and account
  notes
- [`docs/OPERATIONS.md`](docs/OPERATIONS.md) — health checks, storage,
  troubleshooting, and known risks

## Project status

Production uses the checked-in Dockerfile with Python 3.10, one Uvicorn worker,
and Railway's assigned `$PORT`. Railway dashboard settings such as the linked
service, domain, volume, region, and billing controls remain external to this
repository.

Automated coverage is currently limited to focused downloader URL and file
discovery tests in `test_utils.py`.

## License

Apache License 2.0. See [`LICENSE`](LICENSE).
