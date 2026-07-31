# Deployment

## Current deployment record

Owner-provided operational information, recorded on 2026-07-03:

- platform: Railway;
- Railway project dashboard:
  `https://railway.com/project/6811f2fb-e225-48b4-bc2f-017321106faf`;
- repository: `OnePanelOrg/Manga-Panel-Extractor`;
- branch expected in production: `master`;
- Railway account/project cost: **$5 per month**;
- a Railway limit is configured at **10**.

The Railway URL above is an authenticated dashboard link, not the backend's
public API domain. Record the generated public domain separately after
confirming it in the project's service settings.

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
- `/data/images`, `/data/jsons`, and `/data/pages` runtime directories; and
- `DATA_DIR=/data`.

There is no `railway.toml`, `railway.json`, Procfile, CI deployment workflow, or
production domain/service identifier in the repository. The Railway project
dashboard is recorded above, but the health check, region, replicas, volume,
environment variables, public domain, and billing controls must still be
confirmed there.

Comic uploads are sent directly from the browser to the Railway API. Confirm
that Railway's request-size and request-duration limits accommodate
`MAX_UPLOAD_BYTES`, and mount a persistent volume at `/data`; otherwise
normalized uploaded pages and cached extraction results disappear on restart.

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

This confirms the Python process and routing are alive, but does not test Clerk,
Stripe, a chapter source, image processing, persistent storage, or MySQL.

## Variables

Authentication and subscriptions require:

```text
CLERK_ISSUER
CLERK_JWKS_URL
CLERK_AUTHORIZED_PARTIES
STRIPE_SECRET_KEY
STRIPE_PRICE_ID
FRONTEND_URL
```

GPT-5.6 Layout additionally requires server-only vision provider settings:

```text
PANEL_LLM_MODEL=<confirmed provider model identifier>
OPENROUTER_API_KEY=<secret>
```

Confirm the exact provider identifier in the deployment environment before
enabling the frontend label. Never send it to or accept it from the browser.

The Stripe Price must be active, recurring monthly, and exactly €4.99 EUR.
Configure the Stripe Customer Portal in the same Stripe mode as the secret key.

The feedback endpoint requires:

```text
DATABASE_HOST
DATABASE_NAME
DATABASE_USER
DATABASE_PASSWORD
```

For a Railway MySQL service named `MySQL`, configure these reference variables
on the backend service:

```text
DATABASE_HOST=${{MySQL.MYSQLHOST}}
DATABASE_NAME=${{MySQL.MYSQLDATABASE}}
DATABASE_USER=${{MySQL.MYSQLUSER}}
DATABASE_PASSWORD=${{MySQL.MYSQLPASSWORD}}
```

Create the table before enabling the feedback endpoint:

```sql
CREATE TABLE feedback (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    chapter_hash VARCHAR(64) NOT NULL,
    rating TINYINT UNSIGNED NOT NULL,
    comment TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT feedback_rating_range CHECK (rating BETWEEN 0 AND 5),
    INDEX idx_feedback_chapter_hash (chapter_hash)
);
```

The application currently has no migration runner, so this schema must be
applied manually. Failed MySQL connections raise `DatabaseConnectionError` in
the backend logs. Feedback ratings and comments are deliberately excluded from
logs.

No Redis or queue variables are used by the active application.

## Deployment verification checklist

Deploy the API before the freemium frontend. After the API deployment, verify in
this order:

1. Existing legacy chapter hashes still retrieve as public Standard chapters.
2. Anonymous Standard creation and retrieval succeed.
3. Standard and GPT-5.6 Layout produce distinct hashes for the same source URL.
4. Signed-out and free-account premium creation is rejected before extraction.
5. Active Pro premium creation uses the configured server quality model.
6. A signed-in free account can retrieve a premium result, while an anonymous
   caller cannot.
7. Deploy the frontend, then verify upgrade and Checkout continuation flows.

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
- Clerk issuer, JWKS URL, and authorized frontend origins;
- Stripe secret key, €4.99 monthly Price ID, and Customer Portal configuration;
- the exact name, unit, behavior, and notification settings of the limit at 10;
- current plan name, included usage, and expected monthly maximum.

Do not place secret values in this file.
