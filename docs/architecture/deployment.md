# Deployment & Infrastructure

## Overview

This document covers how the application is deployed, how environments are structured, how secrets are managed, and how the production infrastructure is organized. Local development is covered in the tech stack and configuration documents — this document focuses on everything from staging onward.

---

## Environments

| Environment | Purpose | Deployment Trigger |
|---|---|---|
| `local` | Individual developer machines via Docker Compose | Manual |
| `staging` | Pre-production integration testing, QA, and demos | Merge to `main` |
| `production` | Live teacher-facing application | Manual promotion from staging |

### Environment Promotion
- Code flows: `feature branch` → `main` (auto-deploys to staging) → `production` (manual trigger)
- Production deployments require a passing staging smoke test and explicit human approval
- No direct deploys to production — everything goes through staging first

---

## Infrastructure Overview

Hosting provider is not yet decided. The architecture is designed to run on any major cloud provider (AWS, GCP, Azure, Render, Railway, Fly.io, etc.) or a self-hosted environment. All components are containerized and provider-agnostic.

### Candidate Hosting Options

| Option | Best for | Trade-offs |
|---|---|---|
| **AWS** (ECS + RDS + ElastiCache + S3) | Scale, compliance, full control | Most operational overhead |
| **GCP** (Cloud Run + Cloud SQL + Memorystore + GCS) | Similar to AWS, strong managed services | Less familiar tooling for most teams |
| **Render** | Fastest to get running, low ops burden | Less control, fewer compliance certifications |
| **Railway** | Simple deployments, good DX | Limited scale, newer platform |
| **Fly.io** | Good for containerized apps, global edge | Less mature managed DB offering |
| **Self-hosted (VPS + Docker Compose)** | Maximum control, lowest cost | Highest ops burden, backup/HA is manual |

Decision should be made based on: compliance requirements (FERPA), budget, team operational capacity, and required uptime SLA.

### Logical Architecture (provider-agnostic)

```
  ┌──────────┐   HTTPS  ┌──────────────────────────────────────┐
  │  Teacher │ ────────▶│         Load Balancer / Proxy        │
  │  Browser │          └──────────────┬───────────────────────┘
  └──────────┘                         │
                         ┌─────────────▼──────────────────────┐
                         │          Container Runtime          │
                         │                                     │
                         │  ┌──────────┐  ┌────────────────┐  │
                         │  │ Next.js  │  │    FastAPI     │  │
                         │  │ Service  │  │    Service     │  │
                         │  └──────────┘  └───────┬────────┘  │
                         │                        │            │
                         │  ┌─────────────────────▼────────┐  │
                         │  │      Celery Worker(s)        │  │
                         │  └──────────────────────────────┘  │
                         └────────────────────────────────────┘
                                         │
              ┌──────────────────────────┼──────────────────────┐
              │                          │                       │
   ┌──────────▼───────┐    ┌─────────────▼──────┐   ┌──────────▼──────┐
   │   PostgreSQL     │    │      Redis          │   │  Object Storage │
   │  (managed or     │    │  (managed or        │   │  (S3-compatible)│
   │   self-hosted)   │    │   self-hosted)      │   │                 │
   └──────────────────┘    └────────────────────┘   └─────────────────┘
```

---

## Services

### Next.js Frontend
- **Runtime:** Containerized Node.js, built via `next build`
- **Scaling:** Horizontal — add instances on CPU > 70%
- **Health check:** `GET /api/health` → 200

### FastAPI Backend
- **Runtime:** Containerized Python with Gunicorn + Uvicorn workers
- **Workers:** 2 Uvicorn workers per container instance
- **Scaling:** Horizontal — add instances on CPU > 60% or request queue depth
- **Health check:** `GET /api/v1/health` → 200

### Celery Workers
- **Runtime:** Same Docker image as FastAPI, different entry point: `celery -A app.tasks.celery_app worker`
- **Scaling:** 2 instances minimum; scale on Celery queue depth
- **Queues:** `grading` (high priority), `exports` (low priority), `background` (lowest)
- Workers are not behind the load balancer — they pull from Redis queues directly

### PostgreSQL
- **Options:** Managed service (RDS, Cloud SQL, Supabase, Render Postgres) or self-hosted
- **Requirements:** Postgres 16+, `pgvector` extension available, automated daily backups, point-in-time recovery in production
- **Connection pooling:** PgBouncer recommended in production to manage connection limits

### Redis
- **Options:** Managed service (ElastiCache, Upstash, Redis Cloud, Render Redis) or self-hosted
- **Requirements:** Redis 7+, single node is sufficient for Phase 1
- **Persistence:** AOF not required — Redis holds only ephemeral data (queues, progress, sessions). A Redis failure is recoverable without data loss.

### Object Storage
- **Options:** AWS S3, GCP GCS, Cloudflare R2, Backblaze B2, or self-hosted MinIO
- **Requirements:** S3-compatible API (the application uses boto3 with a configurable endpoint), private bucket, pre-signed URL support
- Single bucket per environment, separate by prefix or separate buckets
- Lifecycle policy: auto-delete temporary export files after 24 hours
- Versioning enabled on production bucket

---

## Containerization

### Docker Images
Two images are built from the monorepo:
- `rubric-grading-backend` — FastAPI app + Celery workers (same image, different CMD)
- `rubric-grading-frontend` — Next.js app

Images are built in CI and pushed to a container registry. Options: Docker Hub, GitHub Container Registry (ghcr.io), or a provider-specific registry (ECR, GCR, etc.).

### Image Tagging
- `latest` — most recent build from `main`
- `sha-{git_sha}` — immutable tag for every build
- `v{semver}` — applied manually at release time
- Production deployments always use the `sha-` tag — never `latest`

### Build Process
```
1. CI builds both images on every push to main
2. Images tagged with git SHA and pushed to the container registry
3. Staging services updated with new image SHA (auto-deploy)
4. Production: manual deploy trigger with specific sha- tag
```

---

## CI/CD Pipeline

Using **GitHub Actions** (or equivalent CI platform).

### On every push / PR:
1. Run backend tests (`pytest`)
2. Run frontend tests (`vitest`)
3. Run `pip-audit` and `npm audit`
4. Run linters (`ruff`, `mypy` for backend; `eslint`, `tsc --noEmit` for frontend)

### On merge to `main`:
1. All of the above
2. Build Docker images
3. Push to container registry with `sha-` tag
4. Deploy to staging (mechanism depends on hosting provider)
5. Run staging smoke tests (5 critical E2E tests via Playwright)
6. Notify on failure

### Production deploy (manual):
1. Engineer triggers production deploy with a specific `sha-` tag
2. Hosting platform performs a rolling replacement — old containers stay up until new ones are healthy
3. Smoke tests run against production after deploy
4. Rollback if smoke tests fail (redeploy previous `sha-` tag)

---

## Secrets Management

Secrets must never be stored in source control, Docker images, or CI logs. The specific secrets manager depends on the hosting provider chosen.

| Provider | Secrets Tool |
|---|---|
| AWS | Secrets Manager or Parameter Store |
| GCP | Secret Manager |
| Render / Railway | Environment variable secrets UI |
| Self-hosted | HashiCorp Vault or provider environment injection |
| CI/CD | GitHub Actions encrypted secrets (or equivalent) |

| Secret | Notes |
|---|---|
| `DATABASE_URL` | Injected at container start from secrets manager |
| `REDIS_URL` | Injected at container start |
| `JWT_SECRET_KEY` | Injected at container start |
| `OPENAI_API_KEY` | Injected at container start |
| Object storage credentials | Use IAM roles / workload identity where available; static keys only as a fallback |

Rules:
- No secrets in environment variable files committed to the repository
- No secrets in Docker images
- No secrets in CI/CD logs — mask all secrets in the CI configuration
- Use role-based/workload identity for cloud service access where the hosting provider supports it — avoid static credentials

### Local Dev
Secrets are in a gitignored `.env` file. A `.env.example` with all variable names (no values) is committed. See the configuration document for the minimum local dev set.

---

## Database Migration Strategy

See [migrations.md](migrations.md) for the full strategy. Summary:

- Migrations are run as part of the deployment process, before new application containers start
- A one-off container run (`docker run rubric-grading-backend alembic upgrade head`) executes before the rolling deploy begins
- Migrations must be backward-compatible with the previous application version (zero-downtime deployments)

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

### What is monitored
- Container health (CPU, memory, instance count)
- Load balancer request count, 4xx/5xx error rates, response latency
- PostgreSQL connections, CPU, storage
- Redis memory usage, evictions
- Celery queue depth (published as a custom metric by a lightweight monitor task)
- LLM API error rate and latency (logged by FastAPI workers)

### Alerting thresholds
See [performance.md](performance.md) for the full metric thresholds. Alerts go to the on-call channel (Slack or PagerDuty or equivalent).

### Logging
- All services emit structured JSON logs
- Log aggregation tool is provider-dependent (CloudWatch, GCP Logging, Datadog, Logtail, etc.) — choose based on hosting provider
- No student PII in any log line — reference entity IDs only
- Log retention: 90 days in production

---

## DNS & TLS

- DNS managed via any provider (Cloudflare recommended for DDoS protection and free TLS proxy)
- TLS certificates: auto-provisioned by the hosting platform, or via Let's Encrypt if self-hosting
- Production: `app.{domain}.com`
- Staging: `staging.{domain}.com` — access-restricted by IP allowlist or HTTP basic auth
- API: `api.{domain}.com` or `/api` path prefix on the same domain (decision deferred to hosting choice)
- All HTTP traffic must redirect to HTTPS — enforce at the load balancer or proxy layer
