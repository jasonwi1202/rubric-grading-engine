# Deployment & Infrastructure

## Overview

This document covers how the application is deployed, how environments are structured, how secrets are managed, and how the production infrastructure is organized. Local development is covered in the tech stack and configuration documents — this document focuses on everything from staging onward.

**Hosting provider: [Railway](https://railway.com).** All sections below are Railway-specific. The application is containerized and provider-agnostic, but instructions, variable names, and service configuration assume Railway.

---

## Environments

| Environment | Purpose | Deployment Trigger |
|---|---|---|
| `local` | Individual developer machines via Docker Compose | Manual |
| `staging` | Pre-production integration testing, QA, and demos | Auto-deploy on merge to `main` |
| `production` | Live teacher-facing application | Manual promotion from staging |

Railway models environments natively — a single Railway project contains both `staging` and `production` environments with separate variable sets and separate deployments for each service.

### Environment Promotion
- Code flows: `feature branch` → `main` (auto-deploys to staging) → `production` (manual trigger)
- Production deployments require a passing staging smoke test and explicit human approval
- No direct deploys to production — everything goes through staging first

---

## Railway Project Structure

One Railway **project** contains all services for a given environment. Create two environments in the project: `staging` and `production`.

### Services (per environment)

| Railway Service | Source | Start Command |
|---|---|---|
| `backend` | GitHub repo, root dir `backend/` | `uvicorn app.main:app --host 0.0.0.0 --port $PORT` |
| `worker` | GitHub repo, root dir `backend/` | `celery -A app.tasks.celery_app worker --loglevel=info --concurrency=4` |
| `beat` | GitHub repo, root dir `backend/` | `celery -A app.tasks.celery_app beat --loglevel=info` |
| `frontend` | GitHub repo, root dir `frontend/` | `npm start` (runs `next start`) |
| `postgres` | Railway PostgreSQL **pgvector** template | Managed |
| `redis` | Railway Redis template | Managed |

> **Critical:** Use the **pgvector** Railway template for PostgreSQL, not the standard PostgreSQL template. The application requires the `pgvector` extension for essay embedding similarity. Template: https://railway.com/deploy/3jJFCA

**Object storage:** Use Railway's native **Storage Buckets** (S3-compatible). Create one bucket per environment. Railway provides `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, and the bucket endpoint automatically — reference them from the bucket service variables.

### Private Networking

Services within the same Railway project communicate over the private network using `*.railway.internal` hostnames. Set service-to-service URLs using these private hostnames — do not use public URLs for internal traffic.

| Connection | Variable | Private URL format |
|---|---|---|
| Backend → PostgreSQL | `DATABASE_URL` | Set to Railway's `${{Postgres.DATABASE_URL}}` reference |
| Backend → Redis | `REDIS_URL` | Set to `redis://default:${{Redis.REDISPASSWORD}}@${{Redis.RAILWAY_PRIVATE_DOMAIN}}:6379` |
| Worker → PostgreSQL | `DATABASE_URL` | Same as backend |
| Worker → Redis | `REDIS_URL` | Same as backend |
| Beat → Redis | `REDIS_URL` | Same as backend (broker URL defaults to `REDIS_URL`) |
| Frontend → Backend | `NEXT_PUBLIC_API_URL` | Use the backend's **public** Railway domain (frontend is browser-side) |

---

## Monorepo Configuration

This is a monorepo. Railway needs to know which subdirectory to build for each service. Set the **Root Directory** in each service's Settings:

| Service | Root Directory | Dockerfile path |
|---|---|---|
| `backend` | `backend` | `backend/Dockerfile` |
| `worker` | `backend` | `backend/Dockerfile` (same image, different start command) |
| `beat` | `backend` | `backend/Dockerfile` (same image, different start command) |
| `frontend` | `frontend` | `frontend/Dockerfile` |

Railway auto-detects the `Dockerfile` when present. A `railway.toml` at the repo root provides config-as-code for build and deploy settings — see the file at the root of this repository.

---

## Database Migrations

Railway supports a **pre-deploy command** that runs before the new deployment goes live. Use this to run Alembic migrations with zero downtime.

In the `backend` service settings → Deploy → Pre-deploy command:
```
alembic upgrade head
```

This runs in the same container as the deployment, with all the same environment variables. Migrations are applied before traffic shifts to the new version.

> The `worker` service does **not** need a pre-deploy command — only `backend` runs migrations.

---

## Environment Variables

Railway injects variables from three sources, in priority order:
1. Service-level variables (override everything)
2. Environment-level shared variables (available to all services in the environment)
3. Variable references (`${{ServiceName.VARIABLE_NAME}}` syntax)

### Recommended setup

Set these at the **environment level** (shared across all services) and override per-service where needed:

```
ENVIRONMENT=staging          # or production
LOG_LEVEL=INFO
OPENAI_API_KEY=sk-...
GRADING_PROMPT_VERSION=v1
INTEGRITY_PROVIDER=internal
MAX_ESSAY_FILE_SIZE_MB=10
MAX_BATCH_SIZE=100
CORS_ORIGINS=https://your-frontend.up.railway.app
```

Set these at the **service level** using Railway variable references:

```
# backend and worker services
DATABASE_URL=${{Postgres.DATABASE_URL}}
REDIS_URL=redis://default:${{Redis.REDISPASSWORD}}@${{Redis.RAILWAY_PRIVATE_DOMAIN}}:6379
JWT_SECRET_KEY=<generate with: python -c "import secrets; print(secrets.token_hex(32))">

# S3 / Storage bucket — Railway provides these from the bucket service
AWS_ACCESS_KEY_ID=${{storage-bucket.AWS_ACCESS_KEY_ID}}
AWS_SECRET_ACCESS_KEY=${{storage-bucket.AWS_SECRET_ACCESS_KEY}}
S3_ENDPOINT_URL=${{storage-bucket.RAILWAY_BUCKET_ENDPOINT_URL}}
S3_BUCKET_NAME=${{storage-bucket.RAILWAY_BUCKET_NAME}}
S3_REGION=auto

# frontend service
NEXT_PUBLIC_API_URL=https://<backend-service>.up.railway.app/api/v1
```

---

## Auto-Deploy from GitHub

Railway auto-deploys when commits are pushed to a configured branch:

- `staging` environment → watches `main` branch
- `production` environment → set to manual deploy (no auto-trigger)

Configure in each service's Settings → Source → Watch branch.

CI runs first (GitHub Actions) and must pass before Railway picks up the deployment. This is enforced by not pushing directly to `main` — all merges go through a PR that requires CI to pass.

---

## CI/CD Pipeline

The GitHub Actions CI pipeline (`.github/workflows/ci.yml`) handles testing and linting. Railway handles building and deploying — there is no separate image build/push step in CI.

### On every push / PR:
1. Backend tests (`pytest`), frontend tests (`vitest`)
2. `pip-audit`, `npm audit`
3. Linters: `ruff`, `mypy`, `eslint`, `tsc --noEmit`

### On merge to `main`:
1. All CI checks above
2. Railway auto-triggers staging deploy for `backend`, `worker`, `frontend`
3. Railway runs `alembic upgrade head` pre-deploy on `backend`
4. Rolling deploy — old containers stay live until new ones pass health checks

### Production deploy (manual):
1. Go to Railway dashboard → production environment
2. Click "Deploy" on each service to promote latest `main` build to production
3. Verify health checks pass
4. Run smoke tests against production URL

---

## Secrets Management

All secrets are stored in Railway's environment variable UI — never in source code or Docker images.

| Secret | Where to set |
|---|---|
| `JWT_SECRET_KEY` | Service-level, `backend` and `worker` |
| `OPENAI_API_KEY` | Environment-level (shared) |
| `DATABASE_URL` | Use Railway variable reference `${{Postgres.DATABASE_URL}}` |
| `REDIS_URL` | Constructed from Redis variable references |
| Storage credentials | Use Railway variable references from storage bucket service |

Rules:
- No secrets in `.env` files committed to the repository
- No secrets in Docker images or build args
- Rotate `JWT_SECRET_KEY` by updating the variable — all existing sessions will be invalidated

### Local Dev
Secrets are in a gitignored `.env` file at the project root. Copy `.env.example` and fill in values. See `docs/architecture/configuration.md` for the full variable reference.

---

---

## Rollback

### Application Rollback
Redeploy the previous `sha-` tagged image using the same deploy process. Because images are immutable and tagged by git SHA, any prior build can be redeployed immediately.

### Database Rollback
Database migrations are not automatically rolled back. If a migration introduced a breaking schema change:
1. Deploy a new application version that is compatible with the old schema
2. Write and apply a manual down-migration only if absolutely necessary
3. Down-migrations that drop columns or tables require a multi-step deploy (see migrations document)

---

## Monitoring & Alerting

Railway provides built-in metrics (CPU, memory, network) and log streaming per service in the dashboard.  The application emits **structured JSON log events** for every HTTP request and every Celery queue sample — these are the primary signals for alert rules and dashboards.

---

### Telemetry: structured log events

All telemetry is log-based — no metrics server or agent is required.  Configure your log aggregator (Logtail, Betterstack, Datadog, or equivalent) to receive Railway's log drain and filter on the fields below.

#### `http.request` — one per API request

Emitted by `RequestMetricsMiddleware` for every request **except** the probe paths (`/api/v1/health`, `/api/v1/readiness`).

| Field | Type | Example |
|---|---|---|
| `event` | string | `"http.request"` |
| `method` | string | `"POST"` |
| `path` | string | `"/api/v1/grades/abc/lock"` |
| `status_code` | integer | `200` |
| `latency_ms` | integer | `142` |
| `correlation_id` | string (UUID4) | `"550e8400-…"` |

> **Security:** query strings are never included — they can carry authentication tokens.  Only the URL path is recorded.

#### `celery.queue_depth` — once per minute per queue

Emitted by `tasks.monitor.report_queue_metrics` (Celery Beat, 60-second interval).

| Field | Type | Example |
|---|---|---|
| `event` | string | `"celery.queue_depth"` |
| `queue` | string | `"celery"` |
| `depth` | integer | `3` |

#### `celery.queue_monitor_error` — on Redis failure

Emitted when the queue monitor cannot reach Redis.

| Field | Type | Example |
|---|---|---|
| `event` | string | `"celery.queue_monitor_error"` |
| `error_type` | string | `"ConnectionError"` |

---

### Health and readiness probes

| Endpoint | Purpose | Railway use |
|---|---|---|
| `GET /api/v1/health` | **Liveness** — is the process alive? | Not polled by Railway directly in the current config; available for manual diagnostics and future use |
| `GET /api/v1/readiness` | **Readiness** — is the service ready for traffic? | Railway `healthcheckPath` — gates both container restarts and rolling-deploy traffic cutover |

Both probes return the same JSON envelope shape regardless of HTTP status code.

Liveness probe (`/api/v1/health`) healthy response:

```json
{
  "data": {
    "status": "ok",
    "service": "rubric-grading-engine-api",
    "version": "0.1.0",
    "dependencies": { "database": "ok", "redis": "ok" }
  }
}
```

Readiness probe (`/api/v1/readiness`) healthy response:

```json
{
  "data": {
    "status": "ready",
    "service": "rubric-grading-engine-api",
    "version": "0.1.0",
    "dependencies": { "database": "ok", "redis": "ok" }
  }
}
```

When either dependency is unavailable: HTTP 503, `status` is `"degraded"` (health) or `"not_ready"` (readiness).

Configure Railway's health-check settings per service:

| Service | Health check path | Expected status |
|---|---|---|
| `backend` | `/api/v1/readiness` | 200 — gates both liveness restarts and rolling-deploy traffic cutover |
| `frontend` | `/` | 200 (Next.js default) |
| `worker` | n/a — Railway monitors CPU and memory for Celery workers |
| `beat` | n/a — no HTTP port; Railway monitors CPU and memory |

---

### Alert rules

Ship logs to a log aggregator and create the following alert rules.  Adjust thresholds after observing baseline values in your deployment.

| Signal | Query filter | Threshold | Severity | Action |
|---|---|---|---|---|
| **API error rate high** | `event:"http.request" status_code:>=500` | > 5% of requests over 5 min | 🔴 Critical | Page on-call; check worker and DB logs |
| **API p95 latency high** | `event:"http.request" latency_ms:>2000` | > 10% of requests over 5 min | 🟡 Warning | Investigate DB and LLM call duration |
| **API availability down** | HTTP 503 on `/api/v1/readiness` (external uptime monitor) | Any occurrence | 🔴 Critical | Check Railway health-check; may be an outage |
| **Celery queue depth high** | `event:"celery.queue_depth" queue:"celery" depth:>50` | Any single sample | 🟡 Warning | Check worker process; may need scaling |
| **Celery queue depth critical** | `event:"celery.queue_depth" queue:"celery" depth:>200` | Any single sample | 🔴 Critical | Workers likely down; escalate immediately |
| **Queue monitor failure** | `event:"celery.queue_monitor_error"` | Any occurrence | 🟡 Warning | Redis may be unavailable; check health probe |
| **LLM unavailable** | `error_code:"LLM_UNAVAILABLE"` | > 3 occurrences over 5 min | 🔴 Critical | OpenAI outage or key revoked |
| **LLM parse errors** | `error_code:"LLM_PARSE_ERROR"` | > 5 occurrences over 15 min | 🟡 Warning | Prompt regression; check grading task logs |
| **Health probe degraded** | HTTP 503 on `/api/v1/health` | Any occurrence | 🟡 Warning | DB or Redis connectivity loss |
| **Auth rate-limit flood** | `event:"http.request" path:"/api/v1/auth/login" status_code:429` | > 20 events over 1 min | 🟡 Warning | Possible credential stuffing |

**Acknowledgment expectation:** Critical alerts require acknowledgment within 15 minutes and resolution or rollback decision within 60 minutes.  Warning alerts require acknowledgment within 2 hours during business hours.

**Escalation path:** on-call engineer → lead engineer → incident commander.

---

### Dashboard queries

Use these filters in your log aggregator to build the key on-call dashboards.

#### API availability and error rate

```
# Total request count (last 5 min)
event:"http.request"

# 5xx error count
event:"http.request" status_code:>=500

# 4xx client error count (high volume may indicate a bug)
event:"http.request" status_code:>=400 status_code:<500

# p95 latency proxy: requests slower than 2 s
event:"http.request" latency_ms:>2000
```

#### Celery queue health

```
# Queue depth over time
event:"celery.queue_depth"

# Queue depth for the default queue only
event:"celery.queue_depth" queue:"celery"

# Queue monitor failures (Redis connectivity)
event:"celery.queue_monitor_error"
```

#### Worker and LLM failures

```
# All LLM errors
error_code:"LLM_UNAVAILABLE" OR error_code:"LLM_PARSE_ERROR"

# Grading task failures (look for error_type in Celery worker logs)
logger:"app.tasks.grading" level:"ERROR"

# Worker crash signal (no queue_depth events for > 2 min)
event:"celery.queue_depth"   # alert on absence
```

#### Database and Redis

```
# Health probe degraded (dep failure)
logger:"app.routers.health" level:"WARNING"

# Database connectivity errors
message:"Health check: database unavailable"

# Redis connectivity errors
message:"Health check: Redis unavailable"
```

#### Differentiating failure types

| Symptom | First query | Then check |
|---|---|---|
| API returning 503 | `event:"http.request" status_code:503` | Health probe logs for DB/Redis failure |
| Grading queued but never completes | `event:"celery.queue_depth" depth:>0` | Worker process logs for task errors |
| LLM errors only | `error_code:"LLM_UNAVAILABLE"` | OpenAI status page; check `OPENAI_API_KEY` expiry |
| All services degraded | Health probe HTTP 503 on `/api/v1/health` | Railway dashboard CPU/memory; consider rollback |

---

### Logging

- All services emit structured JSON logs
- Railway streams logs in real time in the dashboard; retained for 7 days on the Pro plan
- For longer retention, forward logs to Logtail or similar via Railway's log drain feature
- **No student PII in any log line** — reference entity IDs only (`student_id`, `essay_id`, `grade_id`)
- Log retention target: 90 days in production (requires external log drain)

---

## DNS & TLS

- Railway provides a free `*.up.railway.app` domain for each service automatically — use these for staging
- For production, add a custom domain in the Railway service settings; Railway provisions TLS automatically via Let's Encrypt
- Recommended DNS provider: Cloudflare (free DDoS protection, TLS proxy)
- Production URLs:
  - Frontend: `app.{yourdomain}.com`
  - Backend API: `api.{yourdomain}.com`
- Staging uses Railway-generated domains (no custom domain needed)
- All HTTP traffic redirects to HTTPS — Railway enforces this automatically on custom domains
