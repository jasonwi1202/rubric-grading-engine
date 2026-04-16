# M1 Release Notes — Technical Reference

**Milestone:** M1 — Project Scaffold
**Version:** v0.2.0 (pending merge to `main`)
**Branch:** `release/m1` → `main`
**Audience:** Engineers, DevOps, security reviewers

---

## PRs Included

| PR | Title | Issues closed |
|---|---|---|
| #17 | [M1.2] Bootstrap FastAPI backend: health endpoint, exception handlers, app factory | #3 |
| #18 | [M1.3] Bootstrap Next.js frontend with security-patched dependencies | #4 |
| #19 | [M1.5] Configure Alembic and async SQLAlchemy session factory | #7 |
| #20 | [M1.7] Set up Celery worker and Redis connection | #10 |
| #21 | [M1.8] Configure S3/MinIO client and bucket | #12 |
| #22 | fix(storage): apply ruff formatting to S3 unit test | — |
| #23 | [M1.10] Implement authentication (frontend) | #16 |

> **Note:** M1.9 (JWT auth backend — `GET /api/v1/auth/*` endpoints) was deferred. The frontend auth wiring is in place (token storage, refresh logic, middleware). The backend JWT issuance endpoints will be delivered in M3.1 or as a standalone issue prior to M3.

---

## New Files and Modules

### Backend (`backend/`)

| Path | Purpose |
|---|---|
| `app/main.py` | FastAPI app factory; mounts routers; registers global exception handlers |
| `app/config.py` | `pydantic-settings` `Settings` class; all env vars with typed defaults |
| `app/exceptions.py` | Domain exception hierarchy; HTTP status mappings |
| `app/routers/health.py` | `GET /api/v1/health` → `{"status": "ok", "version": "..."}` |
| `app/db/session.py` | `AsyncSession` factory (`asyncpg`); `get_db` FastAPI dependency |
| `app/db/migrations/env.py` | Async Alembic env; `autocommit_block()` for `CREATE INDEX CONCURRENTLY` |
| `app/tasks/celery_app.py` | Celery app; broker/result config from `settings` |
| `app/tasks/debug.py` | `ping` smoke-test task |
| `app/storage/s3.py` | `S3Client` wrapper: `upload_file()`, `generate_presigned_url()` |

### Frontend (`frontend/`)

| Path | Purpose |
|---|---|
| `lib/api/client.ts` | Typed API client; attaches Bearer token; handles 401 → silent refresh → retry |
| `lib/api/baseFetch.ts` | Raw fetch wrapper; validates response shape; throws typed `ApiError` |
| `lib/api/errors.ts` | `ApiError` class with structured error fields |
| `lib/auth/session.ts` | In-memory access token store; `getAccessToken()`, `setAccessToken()`, `clearSession()` |
| `lib/schemas/auth.ts` | Zod schemas for login form and API response |
| `lib/utils/redirect.ts` | `isSafeRedirectPath()` — open-redirect guard |
| `lib/utils/cn.ts` | Tailwind class merge utility |
| `middleware.ts` | Next.js middleware; enforces auth on `/(dashboard)/*`; allows public routes |
| `app/(auth)/login/page.tsx` | Login form; React Hook Form + Zod; calls `POST /api/v1/auth/login` |
| `app/(dashboard)/layout.tsx` | Dashboard shell layout (stub — no sidebar yet) |
| `components/providers.tsx` | `QueryClientProvider` wrapper |

---

## Configuration Changes

New environment variables added (see `docs/architecture/configuration.md` for full reference):

**Backend:**
- `DATABASE_URL` — asyncpg connection string
- `REDIS_URL` — Celery broker and result backend
- `S3_ENDPOINT_URL`, `S3_BUCKET_NAME`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` — file storage
- `SECRET_KEY` — used for JWT signing (M1.9/M3 will consume this)
- `ENVIRONMENT` — `development` | `staging` | `production`

**Frontend:**
- `NEXT_PUBLIC_API_URL` — base URL of the backend API
- `NEXT_PUBLIC_APP_ENV` — passed to client-side code

---

## Test Coverage

### Backend unit tests
- `test_config.py` — settings loading, env var override, defaults
- `test_main.py` — health endpoint, exception handler responses, 404/405 shapes
- `test_session.py` — session factory construction, `get_db` dependency
- `test_celery_app.py` — broker config, result backend config, task registration
- `test_s3.py` — upload, presigned URL generation, error handling (unit, mocked boto3)

### Backend integration tests
- `test_s3.py` (integration) — real MinIO via `testcontainers`; upload → presigned URL → HTTP GET

### Frontend unit tests
- `api-client.test.ts` — token attachment, 401 refresh-and-retry, refresh failure redirect, error parsing
- `session.test.ts` — token set/get/clear, cross-tab isolation, no `localStorage` leakage
- `redirect.test.ts` — safe and unsafe redirect path detection, backslash normalisation

### Coverage gaps (known, acceptable for this milestone)
- No E2E tests yet — Playwright scaffold is MX.3
- No auth backend tests — M1.9 is deferred; tests will accompany those endpoints
- No database integration tests — no application tables exist yet (M3.1)

---

## Security Notes

| Area | Status |
|---|---|
| Secrets in source | ✅ None — all via `settings.*` |
| Student PII in logs | ✅ S3 keys excluded; no student data exists yet |
| `npm audit` | ✅ Clean (Next.js upgraded 14→15 to resolve 2 DoS CVEs) |
| `pip-audit` | ✅ Clean |
| Access token storage | ✅ In-memory only; no `localStorage`/`sessionStorage` |
| Open-redirect guard | ✅ `isSafeRedirectPath()` on all post-login redirects |
| CORS | ⏳ Not yet configured — no cross-origin requests exist yet; MX.1 |
| Security headers | ⏳ Not yet configured — MX.1 |
| RLS policies | ⏳ No tables yet — M3.1 |

---

## Deferred from M1

| Item | Reason | Planned for |
|---|---|---|
| `POST /api/v1/auth/login`, `/refresh`, `/logout` (JWT issuance) | Copilot agent scoped M1.9 into M1.8 S3 branch; auth endpoints need `users` table | M3 or pre-M3 issue |
| `get_current_teacher` FastAPI dependency | Depends on JWT endpoints and `users` table | M3 |
| Teacher registration / password hashing | Depends on `users` table | M3.1 / M2.8 |

---

## How to Verify Locally

```bash
# Start all services
docker compose up -d

# Backend health check
curl http://localhost:8000/api/v1/health
# → {"status":"ok","version":"..."}

# Backend unit tests
cd backend && python -m pytest tests/unit -v

# Backend integration tests (requires Docker)
cd backend && python -m pytest tests/integration -v

# Frontend
cd frontend && npm run build && npm test
```

---

## Breaking Changes

None. This is the initial scaffold — no existing APIs or schemas were modified.
