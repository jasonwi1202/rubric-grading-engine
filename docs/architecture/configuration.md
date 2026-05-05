# Configuration

## Overview

All configuration is environment-driven. No secrets or environment-specific values are hardcoded in application code. This document defines every configuration variable, its purpose, and its expected values.

---

## Principles

- **Twelve-factor app config** — everything that varies between environments (local, staging, production) is an environment variable
- **Fail fast** — the application refuses to start if required variables are missing or invalid
- **No defaults for secrets** — API keys, database passwords, and signing secrets have no fallback defaults. Missing = crash on startup.
- **Sensible defaults for tuning values** — timeouts, page sizes, retry counts have sane defaults that work in development

---

## Backend Configuration

Managed via `pydantic-settings` in `backend/app/config.py`. All variables are validated at startup.

### Database

| Variable | Required | Default | Description |
|---|---|---|---|
| `DATABASE_URL` | Yes | — | PostgreSQL connection string. Format: `postgresql+asyncpg://user:password@host:port/dbname` |
| `DATABASE_POOL_SIZE` | No | `10` | SQLAlchemy connection pool size |
| `DATABASE_MAX_OVERFLOW` | No | `20` | Max connections above pool size |

### Redis

| Variable | Required | Default | Description |
|---|---|---|---|
| `REDIS_URL` | Yes | — | Redis connection string. Format: `redis://host:port/db` |
| `REDIS_GRADING_TTL_SECONDS` | No | `3600` | TTL for batch grading progress keys in Redis |

### Authentication

| Variable | Required | Default | Description |
|---|---|---|---|
| `JWT_SECRET_KEY` | Yes | — | Secret for signing JWT access tokens. Min 32 chars. |
| `JWT_ALGORITHM` | No | `HS256` | JWT signing algorithm |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | No | `15` | Access token TTL in minutes |
| `REFRESH_TOKEN_EXPIRE_DAYS` | No | `7` | Refresh token TTL in days |

### LLM / OpenAI

| Variable | Required | Default | Description |
|---|---|---|---|
| `OPENAI_API_KEY` | Yes | — | OpenAI API key |
| `OPENAI_GRADING_MODEL` | No | `gpt-4o` | Model used for grading and feedback generation |
| `OPENAI_EMBEDDING_MODEL` | No | `text-embedding-3-small` | Model used for essay embeddings (similarity detection) |
| `LLM_REQUEST_TIMEOUT_SECONDS` | No | `60` | Timeout for individual LLM API calls |
| `LLM_MAX_RETRIES` | No | `3` | Max retry attempts on LLM failure |
| `GRADING_PROMPT_VERSION` | No | `v1` | Active prompt version — must match a file in `llm/prompts/` |

### File Storage (S3)

| Variable | Required | Default | Description |
|---|---|---|---|
| `S3_BUCKET_NAME` | Yes | — | S3 bucket for all file storage |
| `S3_REGION` | Yes | — | AWS region (or `us-east-1` for MinIO) |
| `AWS_ACCESS_KEY_ID` | Yes | — | AWS / MinIO access key |
| `AWS_SECRET_ACCESS_KEY` | Yes | — | AWS / MinIO secret key |
| `S3_ENDPOINT_URL` | No | — | Override endpoint URL for MinIO local dev (e.g., `http://minio:9000`) |
| `S3_PRESIGNED_URL_EXPIRE_SECONDS` | No | `3600` | TTL for generated download URLs |

### Celery

| Variable | Required | Default | Description |
|---|---|---|---|
| `CELERY_BROKER_URL` | No | `$REDIS_URL` | Celery broker URL — defaults to Redis |
| `CELERY_RESULT_BACKEND` | No | `$REDIS_URL` | Celery result backend — defaults to Redis |
| `CELERY_WORKER_CONCURRENCY` | No | `4` | Number of concurrent Celery worker processes |
| `CELERY_RESULT_EXPIRES_SECONDS` | No | `3600` | TTL (seconds) before completed task results are removed from the backend |
| `GRADING_TASK_SOFT_TIME_LIMIT` | No | `120` | Soft time limit (seconds) for a single grading task before warning |
| `GRADING_TASK_HARD_TIME_LIMIT` | No | `180` | Hard time limit (seconds) before Celery kills the task |

### Integrity Checking

| Variable | Required | Default | Description |
|---|---|---|---|
| `INTEGRITY_PROVIDER` | No | `internal` | Which integrity service to use: `internal`, `originality_ai`, or `winston_ai` |
| `INTEGRITY_API_KEY` | Conditional | — | Required if `INTEGRITY_PROVIDER` is not `internal` |
| `INTEGRITY_SIMILARITY_THRESHOLD` | No | `0.25` | Similarity score above which an essay is flagged (0.0–1.0) |
| `INTEGRITY_AI_LIKELIHOOD_THRESHOLD` | No | `0.7` | AI likelihood score above which an essay is flagged (0.0–1.0) |

### Application

| Variable | Required | Default | Description |
|---|---|---|---|
| `ENVIRONMENT` | No | `development` | `development`, `staging`, or `production` |
| `LOG_LEVEL` | No | `INFO` | Python logging level |
| `CORS_ORIGINS` | Yes | — | Comma-separated list of allowed CORS origins |
| `MAX_ESSAY_FILE_SIZE_MB` | No | `10` | Max file size for essay uploads |
| `MAX_BATCH_SIZE` | No | `100` | Max essays per grading batch |
| `TRUST_PROXY_HEADERS` | No | `false` | When `true`, read the real client IP from `CF-Connecting-IP` / `X-Forwarded-For` (enable only in production behind a trusted proxy such as Cloudflare) |
| `REGRADE_WINDOW_DAYS` | No | `7` | Number of days after a grade is created during which regrade requests are accepted. Requests submitted after this window return 409. |
| `REGRADE_MAX_PER_GRADE` | No | `1` | Maximum number of regrade requests allowed per grade. Additional submissions after this limit return 409. |

### Test-Only Controls

These variables are blocked in `staging` and `production` by a startup validator and must never be set in those environments.

| Variable | Required | Default | Description |
|---|---|---|---|
| `LLM_FAKE_MODE` | No | `false` | Bypass real OpenAI calls; return deterministic synthetic outputs. Use in CI E2E and unit tests. Blocked in staging/production by the startup validator. |
| `EXPORT_TASK_FORCE_FAIL` | No | `false` | **Test-only.** When `true`, enables the internal test-control router (`POST /api/v1/internal/export-test-controls/arm-failure`) for one-shot export failure injection (failure → retry → success flow). Tasks do **not** fail unconditionally — arm the endpoint to trigger a single failure; subsequent exports proceed normally. Cannot be `true` in `staging` or `production`. |
| `ALLOW_UNVERIFIED_LOGIN_IN_TEST` | No | `false` | Skip email-verification check on login. CI E2E bypass when email delivery is intentionally bypassed. |
| `SHORT_LIVED_TOKEN_TTL_SECONDS` | No | *(unset)* | **Test-only.** When set to a positive integer, overrides the access-token TTL for all tokens issued by `/auth/login` and `/auth/refresh` (in seconds instead of the default 15-minute TTL). Use in CI E2E to exercise the token-expiry → silent-refresh recovery path deterministically. Must not be set in `staging` or `production` (enforced by the startup validator). |

#### Using `EXPORT_TASK_FORCE_FAIL` for E2E failure injection

Setting `EXPORT_TASK_FORCE_FAIL=true` registers the test-only internal router
and activates the per-assignment one-shot failure check in the export Celery
task.  Tasks do **not** fail automatically — a failure must be explicitly armed
via the endpoint:

**One-shot failure (per-assignment):** The arm endpoint accepts an `assignment_id`
and sets a Redis key scoped to that assignment (TTL: 5 minutes). The next export
task for that assignment atomically consumes the key and fails with
`FORCED_FAILURE`. Subsequent exports (including the retry) proceed normally.
Use this to exercise the full **failure → retry → success** flow in a single
test run. Because the key is scoped to the assignment, parallel Playwright
workers arming different assignments cannot consume each other's flags.

**Local dev:**
```bash
# Add to .env and restart backend + worker containers:
EXPORT_TASK_FORCE_FAIL=true

# Then run the failure injection E2E spec:
cd frontend
npx playwright test mx8-04-export-failure-injection
```

**CI (GitHub Actions / Docker Compose E2E):**

Add `EXPORT_TASK_FORCE_FAIL=true` to your `.env.ci` or Docker Compose environment override for the
shard that runs the failure injection spec. The arm-failure endpoint is not registered when the flag is
not set, so other specs are unaffected.

```bash
# .env.ci override (or docker-compose.ci.yml environment section):
EXPORT_TASK_FORCE_FAIL=true
```

The Playwright spec (`mx8-04-export-failure-injection.spec.ts`) probes the arm-failure endpoint
before running and skips gracefully when `EXPORT_TASK_FORCE_FAIL` is not enabled.

#### Using `SHORT_LIVED_TOKEN_TTL_SECONDS` for E2E token-expiry testing

Setting `SHORT_LIVED_TOKEN_TTL_SECONDS=<seconds>` causes every `/auth/login` and `/auth/refresh`
call to issue a JWT that expires after `<seconds>` instead of the standard 15 minutes.  This lets
the `mx8-05-short-lived-token` Playwright spec exercise real token-expiry events deterministically
in CI without waiting 15 minutes.

**Behaviour:** All tokens issued by the backend while this setting is active are short-lived.
The spec probes this by decoding the freshly issued JWT's `exp − iat` claims; if the result exceeds
30 seconds the spec considers the feature inactive and skips gracefully.  Run this spec in an
isolated CI shard so the short TTL does not cause spurious 401s in other concurrent specs.

**Local dev:**
```bash
# Add to .env and restart the backend container:
SHORT_LIVED_TOKEN_TTL_SECONDS=3

# Then run the short-lived token E2E spec:
cd frontend
npx playwright test mx8-05-short-lived-token
```

**CI (GitHub Actions / Docker Compose E2E):**

Add `SHORT_LIVED_TOKEN_TTL_SECONDS=3` to your `.env.ci` or Docker Compose environment override for
the shard that runs `mx8-05-short-lived-token.spec.ts`.  Other shards that do not set this variable
continue to receive 15-minute tokens and are unaffected.

```bash
# .env.ci override (or docker-compose.ci.yml environment section for the token-expiry shard):
SHORT_LIVED_TOKEN_TTL_SECONDS=3
ALLOW_UNVERIFIED_LOGIN_IN_TEST=true   # bypass email delivery in CI
```

The spec skips gracefully when `SHORT_LIVED_TOKEN_TTL_SECONDS` is not enabled, so it is safe to
include in a full E2E run — it will no-op unless the backend is configured for short-lived mode.

### Skill Normalization

| Variable | Required | Default | Description |
|---|---|---|---|
| `SKILL_NORMALIZATION_CONFIG_PATH` | No | — | Absolute path to a custom JSON skill-normalization mapping file. When not set, the bundled `app/skill_normalization_config.json` is used (English writing dimensions: `thesis`, `evidence`, `organization`, `analysis`, `mechanics`, `voice`). Override for non-English subjects or custom rubric vocabularies. See `docs/architecture/data-ingestion.md#4-skill-normalization`. |

### Email / SMTP

| Variable | Required | Default | Description |
|---|---|---|---|
| `EMAIL_VERIFICATION_HMAC_SECRET` | Yes | — | Secret for HMAC-signing single-use email verification tokens. Min 32 chars. Generate with: `python -c "import secrets; print(secrets.token_hex(32))"` |
| `UNSUBSCRIBE_HMAC_SECRET` | Yes | — | Secret for HMAC-signing unsubscribe tokens on non-transactional emails (trial warnings, expiry). Min 32 chars. Should be different from `EMAIL_VERIFICATION_HMAC_SECRET`. |
| `VERIFICATION_TOKEN_TTL_SECONDS` | No | `86400` | TTL (seconds) for email verification tokens stored in Redis — defaults to 24 hours |
| `FRONTEND_URL` | No | `http://localhost:3000` | Base URL of the frontend — used to build links in emails (verification, unsubscribe, "Get Started") |
| `VERIFICATION_EMAIL_FROM` | No | — | "From" address for outbound emails. Falls back to `CONTACT_EMAIL` if not set. If neither is configured, email tasks are skipped (no-op). |
| `CONTACT_EMAIL` | No | — | Email address that receives school/district inquiry and DPA request notifications. Also used as fallback sender for teacher-facing emails. |
| `SMTP_HOST` | No | `localhost` | SMTP server hostname |
| `SMTP_PORT` | No | `25` | SMTP server port |
| `SMTP_TIMEOUT` | No | `10` | Timeout (seconds) for SMTP connections — prevents hung Celery workers |
| `SMTP_USER` | No | — | SMTP username for authenticated servers. Leave unset for unauthenticated relays. |
| `SMTP_PASSWORD` | No | — | SMTP password for authenticated servers. Leave unset for unauthenticated relays. |

---

## Frontend Configuration

Next.js environment variables. Variables prefixed with `NEXT_PUBLIC_` are exposed to the browser — treat them as public. All others are server-only.

| Variable | Required | Default | Description |
|---|---|---|---|
| `NEXT_PUBLIC_API_URL` | Yes | — | Base URL of the FastAPI backend (e.g., `https://api.example.com/api/v1`) |
| `NEXT_PUBLIC_APP_ENV` | No | `development` | `development`, `staging`, `production` — controls feature flags and logging |
| `GRADING_POLL_INTERVAL_MS` | No | `3000` | How often the frontend polls grading status (server-side only, passed to client as config) |

**Important:** No API keys or secrets belong in Next.js environment variables. All sensitive operations go through the FastAPI backend.

---

## Local Development

All local dev configuration lives in a `.env` file at the project root (gitignored). A `.env.example` file with all variables listed (but no real values) is committed to the repository.

### Docker Compose Services and Their Config
```
postgres     → DATABASE_URL
redis        → REDIS_URL, CELERY_BROKER_URL, CELERY_RESULT_BACKEND
minio        → S3_ENDPOINT_URL, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, S3_BUCKET_NAME
backend      → all backend variables above
worker       → DATABASE_URL, REDIS_URL, OPENAI_API_KEY, S3_* (same image as backend, different command)
frontend     → NEXT_PUBLIC_API_URL
```

### Minimum viable `.env` for local dev
```bash
# Database
DATABASE_URL=postgresql+asyncpg://postgres:postgres@postgres:5432/rubric_grading

# Redis
REDIS_URL=redis://redis:6379/0

# Auth
JWT_SECRET_KEY=local-dev-secret-change-in-production-minimum-32-chars

# OpenAI
OPENAI_API_KEY=sk-...

# S3 / MinIO
S3_BUCKET_NAME=rubric-grading-local
S3_REGION=us-east-1
AWS_ACCESS_KEY_ID=minioadmin
AWS_SECRET_ACCESS_KEY=minioadmin
S3_ENDPOINT_URL=http://minio:9000

# Email verification
EMAIL_VERIFICATION_HMAC_SECRET=local-dev-hmac-secret-change-in-production-32c

# Trial lifecycle emails (unsubscribe tokens)
UNSUBSCRIBE_HMAC_SECRET=local-dev-unsub-secret-change-in-production-32ch

# Frontend
NEXT_PUBLIC_API_URL=http://localhost:8000/api/v1

# CORS
CORS_ORIGINS=http://localhost:3000
```

---

## Configuration Validation

The backend uses `pydantic-settings` to validate all config at startup:
- Missing required variables raise `ValidationError` with a clear message listing what is missing
- `JWT_SECRET_KEY` must be at least 32 characters — shorter keys are rejected
- `EMAIL_VERIFICATION_HMAC_SECRET` must be at least 32 characters
- `UNSUBSCRIBE_HMAC_SECRET` must be at least 32 characters
- `ENVIRONMENT` must be one of the allowed values
- `OPENAI_GRADING_MODEL` is validated against a list of known-supported models

The application will not start with invalid configuration. This is intentional — silent misconfiguration in production is worse than a startup crash.
