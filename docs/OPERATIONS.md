# Operations

## Service checks

Basic liveness:

```sh
curl https://<railway-domain>/
```

Expected response:

```json
{"Hello":"World"}
```

Functional processing check:

```sh
curl -X POST https://<railway-domain>/v2/chapter \
  -H 'content-type: application/json' \
  -d '{"chapter_url":"<known-compatible-chapter-url>"}'
```

Expected response:

```json
{"chapter_hash":"<32-character-md5>"}
```

Then retrieve it with `GET /v2/chapter/<chapter_hash>`.

Use a chapter that the project is authorized to fetch. A functional check makes
external requests and consumes CPU, memory, disk, and Railway usage.

## Storage behavior

Downloaded images are temporary and are removed immediately after extraction,
including when extraction fails. Generated Kumiko JSON and rotating logs remain
in the local working directory. Unless Railway has a persistent volume mounted,
these files can disappear on redeploy or restart. With multiple replicas, a
result written by one replica may not be available to another.

Historical cache directories may still contain `panel_extracted.json` from the
removed OpenCV extraction path. The application no longer reads or writes that
file, so it can be deleted during cache maintenance.

Cache keys ignore URL query strings. Two URLs that differ only by query
parameters intentionally share one result. There is no cache expiration or
cleanup, so disk usage grows with each distinct chapter.

## Logging

`app.py` logs both to standard output and to `OnePanelLogs`, rotating at
midnight. Railway's standard-output logs are the primary operational record.
The local file is subject to the same persistence and disk-growth limitations
as other local data.

The service logs chapter hashes, request IDs, and a generic event when feedback
is received. It does not log feedback ratings or comments because comments may
contain user-provided or sensitive text.

## Failure guide

| Symptom | Likely cause |
| --- | --- |
| Service does not become healthy | Start command does not bind to `$PORT`, dependency/build failure, or application import failure |
| Chapter returns HTTP 422 with no supported images | Source images do not match the supported `https://i*.png`/`https://i*.webp` pattern, site HTML changed, or lazy-loaded images use another attribute |
| Request fails after a restart | Local cache was ephemeral |
| `GET /v2/chapter/{hash}` returns 404 | Hash was never generated on this instance, cache was lost, or another replica owns it |
| Chapter request is slow or times out | Downloads and CPU-heavy image processing run synchronously |
| Feedback request returns 500 with `DatabaseConnectionError` in the service logs | Missing/invalid MySQL variables or database unavailable |
| Feedback request returns 500 with a MySQL table error in the service logs | The `feedback` table has not been created or its schema is incompatible |
| Existing image directory causes later failure | `download_lmages()` returns early even if `img_dict.json` or images are incomplete |

## Known technical risks

1. Network calls have no timeout, retry, status validation, content limit, or
   URL allowlist. A caller controls the chapter URL, making SSRF and resource
   exhaustion relevant production risks.
2. Endpoints have no authentication or rate limiting.
3. Processing blocks the request worker and can consume substantial memory.
4. Local state is not safe for ephemeral or horizontally scaled deployment.
5. CORS is hard-coded. Star patterns in `allow_origins` are literal strings,
   not wildcard host matching.
6. `GET /v2/chapter/{hash}` assumes `jsons/` exists and directly reads files.
7. Feedback connects synchronously on every request and has no retry policy.
8. Dependencies are pinned to 2023-era versions and need a deliberate security
   and compatibility upgrade.
9. There is no production-grade automated test suite or deployment smoke test.

Empty extraction results are rejected with HTTP 422 and are not written to the
chapter cache.

## Recommended next engineering steps

1. Confirm and capture the Railway dashboard configuration.
2. Confirm Railway builds the checked-in Dockerfile and mounts durable storage
   at `/data`.
3. Move generated data to durable object/database storage.
4. Add URL validation, request timeouts, response limits, authentication, and
   rate limiting.
5. Move extraction into a background job with explicit job status.
6. Add isolated tests for URL normalization, downloading, panel output, cache
   behavior, and every API endpoint.
7. Add cache retention/cleanup and operational metrics.
