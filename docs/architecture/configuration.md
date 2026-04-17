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
- `ENVIRONMENT` must be one of the allowed values
- `OPENAI_GRADING_MODEL` is validated against a list of known-supported models

The application will not start with invalid configuration. This is intentional — silent misconfiguration in production is worse than a startup crash.
