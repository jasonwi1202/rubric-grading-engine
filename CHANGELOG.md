# Changelog

All notable changes to this project are documented here. This file is updated automatically by the `milestone-release.yml` workflow when a release branch is merged to `main`, and manually for hotfixes.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versions follow `v0.{milestone+1}.0` (e.g. M0 → v0.1.0, M1 → v0.2.0).

---

## [Unreleased]

Changes on active feature branches not yet merged to a release branch.

---

## [v0.2.0] — M1 Project Scaffold — Unreleased (pending merge to main)

### Added
- **FastAPI backend bootstrap** — app factory pattern, `GET /api/v1/health` endpoint, structured JSON error responses for all unhandled exceptions (`app/main.py`, `app/exceptions.py`, `app/routers/health.py`)
- **pydantic-settings configuration layer** — `app/config.py` loads all environment variables with typed defaults; secrets accessed only via `settings.*`, never `os.environ` directly
- **Async SQLAlchemy session factory** — `app/db/session.py` using `asyncpg` driver; `AsyncSession` available for all database operations
- **Alembic migration scaffold** — `alembic.ini`, `app/db/migrations/env.py` with async migration support and `autocommit_block()` for `CREATE INDEX CONCURRENTLY`
- **Celery worker + Redis broker** — `app/tasks/celery_app.py`; smoke-test `ping` task in `app/tasks/debug.py`; all broker/result config from `settings`
- **S3/MinIO client wrapper** — `app/storage/s3.py` with `upload_file()` and `generate_presigned_url()`; configurable endpoint for both AWS S3 and MinIO; no credentials hardcoded
- **Next.js 15 frontend bootstrap** — TypeScript, App Router, Tailwind CSS, shadcn/ui, TanStack Query v5, React Hook Form, Zod; `/(auth)/` and `/(dashboard)/` route groups
- **Typed API client** — `frontend/lib/api/client.ts` and `lib/api/baseFetch.ts`; all API calls go through this layer; silent JWT refresh on 401; no raw `fetch` in components
- **Frontend auth** — Login page (`/login`), `middleware.ts` protecting `/(dashboard)/*`, in-memory token storage, `lib/auth/session.ts`, `lib/utils/redirect.ts` with open-redirect guard
- **Backend + frontend Dockerfiles** — production-ready multi-stage builds for both services

### Security
- Next.js upgraded 14.2.35 → 15.5.15 to patch two DoS CVEs flagged by `npm audit`
- S3 object keys never appear in logs or error messages (FERPA compliance)
- Access tokens stored in memory only — never in `localStorage`, `sessionStorage`, or cookies
- Open-redirect guard on all post-login redirect destinations
- All secrets read from `settings.*`; `os.environ` access blocked by convention

### Tests added
- `backend/tests/unit/` — `test_config.py`, `test_main.py`, `test_session.py`, `test_celery_app.py`, `test_s3.py`
- `backend/tests/integration/test_s3.py` — MinIO testcontainer integration test
- `frontend/tests/unit/` — `api-client.test.ts`, `session.test.ts`, `redirect.test.ts`

---

<!-- Milestone releases are prepended here automatically by the release workflow -->
