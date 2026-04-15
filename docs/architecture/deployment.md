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
| Frontend → Backend | `NEXT_PUBLIC_API_URL` | Use the backend's **public** Railway domain (frontend is browser-side) |

---

## Monorepo Configuration

This is a monorepo. Railway needs to know which subdirectory to build for each service. Set the **Root Directory** in each service's Settings:

| Service | Root Directory | Dockerfile path |
|---|---|---|
| `backend` | `backend` | `backend/Dockerfile` |
| `worker` | `backend` | `backend/Dockerfile` (same image, different start command) |
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

Railway provides built-in metrics (CPU, memory, network) and log streaming per service in the dashboard.

### What to monitor
- Container health — Railway dashboard shows CPU, memory, and restart counts per service
- HTTP error rates — structured logs from FastAPI; filter for `status_code >= 400`
- Celery queue depth — published as a custom metric by a lightweight monitor task; alert if grading queue > 50 for > 5 minutes
- LLM API error rate and latency — logged by FastAPI workers; alert on sustained `LLM_UNAVAILABLE` errors
- PostgreSQL storage — Railway dashboard; alert at 80% capacity

### Alerting
Railway supports **webhooks** for deployment events. For metric-based alerting, ship logs to an external aggregator (Logtail, Datadog, or Betterstack are good Railway-compatible options).

### Logging
- All services emit structured JSON logs
- Railway streams logs in real time in the dashboard; retained for 7 days on the Pro plan
- For longer retention, forward logs to Logtail or similar via Railway's log drain feature
- **No student PII in any log line** — reference entity IDs only
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
