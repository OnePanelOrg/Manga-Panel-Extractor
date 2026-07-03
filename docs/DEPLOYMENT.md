# Deployment

## Current deployment record

Owner-provided operational information, recorded on 2026-07-03:

- platform: Railway;
- repository: `OnePanelOrg/Manga-Panel-Extractor`;
- branch expected in production: `master`;
- Railway account/project cost: **$5 per month**;
- a Railway limit is configured at **10**.

The meaning and unit of “limit at 10” were not available in the repository. It
may refer to a spending/usage limit or another Railway project limit. Verify the
exact dashboard setting before relying on it for cost control. This document
intentionally does not assign a dollar unit or a formal Railway plan name
without dashboard evidence.

## What is and is not versioned

The repository includes:

- a Dockerfile based on `python:3.10-slim`;
- required OpenCV system libraries;
- a single-worker Uvicorn start command bound to `${PORT:-8000}`;
- `/data/images` and `/data/jsons` runtime directories; and
- `DATA_DIR=/data`.

There is no `railway.toml`, `railway.json`, Procfile, CI deployment workflow, or
production domain/service identifier. The health check, region, replicas,
volume, environment variables, domain, and billing controls must still be
confirmed in the Railway dashboard.

## Expected service configuration

The application import target is:

```text
app:app
```

The Dockerfile starts the service with:

```sh
uvicorn app:app --host 0.0.0.0 --port "${PORT:-8000}" --workers 1
```

The former local `start.sh` was not Railway-compatible and has been removed.

Suggested health-check path:

```text
/
```

This confirms the Python process and routing are alive, but does not test a
chapter source, image processing, persistent storage, or MySQL.

## Variables

The core chapter endpoints have no declared secrets. The feedback endpoint
requires:

```text
DATABASE_HOST
DATABASE_NAME
DATABASE_USER
DATABASE_PASSWORD
```

No Redis or queue variables are used by the active application.

## Deployment verification checklist

In Railway, record or verify:

- linked GitHub repository and production branch;
- deployed commit SHA matches the intended `master` revision;
- Railway is building the checked-in Dockerfile;
- public domain;
- `$PORT` binding;
- health-check path and restart policy;
- replica count and resource allocation;
- whether a persistent volume is mounted for `images/`, `jsons/`, and logs;
- database variables, if feedback is enabled;
- the exact name, unit, behavior, and notification settings of the limit at 10;
- current plan name, included usage, and expected monthly maximum.

Do not place secret values in this file.
