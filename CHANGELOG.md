# Changelog

All notable changes to this project are documented here. This file is updated automatically by the `milestone-release.yml` workflow when a release branch is merged to `main`, and manually for hotfixes.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versions follow `v0.{milestone+1}.0` (e.g. M0 → v0.1.0, M1 → v0.2.0).

---

## [Unreleased]

Changes on active feature branches not yet merged to a release branch.

---

## [v0.3.0] — M2 Public Website & Onboarding — Unreleased (pending merge to main)

### Added
- **Public site layout** — `/(public)/` route group with shared header (Product, How It Works, Pricing, AI, About, Sign In, Start Trial CTA) and footer; `PRODUCT_NAME` constant; middleware redirects authenticated users from `/login` and `/signup` to `/dashboard`
- **Landing page (`/`)** — hero, problem/solution, feature highlight cards, how-it-works steps, and CTA section; fully static
- **Product & How It Works pages** — `/product` feature deep-dive with screenshot placeholders and trust callout; `/how-it-works` numbered workflow timeline
- **About page (`/about`)** — mission statement, core principles, team placeholder, contact callout
- **Pricing page (`/pricing`)** — tier cards (Trial/Teacher/School/District), annual/monthly toggle, feature comparison table, FAQ accordion; school inquiry form posts to `POST /api/v1/contact/inquiry`
- **AI transparency page (`/ai`)** — 5-step grading explanation, HITL guarantee callout, data use disclosure, confidence score explainer
- **Legal pages (`/legal/*`)** — Terms of Service, Privacy Policy, FERPA/COPPA Notice, DPA info page (with DPA request form → `POST /api/v1/contact/dpa-request`), AI Use Policy; `[ATTORNEY DRAFT REQUIRED]` banner on all pages
- **Sign-up flow** — `POST /api/v1/auth/signup` (bcrypt, email verification Celery task, 201); `GET /api/v1/auth/verify-email` (HMAC-signed token, Redis TTL); `POST /api/v1/auth/resend-verification`; `/signup`, `/signup/verify`, `/auth/verify` pages; rate-limited to 5 attempts/IP/hour
- **Onboarding wizard** — `/(onboarding)/` route group; 2-step wizard (create class → build rubric or skip); `GET /api/v1/onboarding/status`; `POST /api/v1/onboarding/complete`; `/onboarding/done` completion page; trial status banner in dashboard layout
- **Trial lifecycle emails** — Celery tasks for welcome, 7-day warning, 1-day warning, and day-0 expiry emails; Celery Beat schedule for daily scan; plain HTML via SMTP; unsubscribe link on non-transactional emails; `GET /api/v1/account/trial` endpoint
- **Contact & DPA backend** — `POST /api/v1/contact/inquiry` and `POST /api/v1/contact/dpa-request` with Redis rate limiting, Pydantic validation, audit log entries, and Celery notification email tasks
- **`email-validator` dependency** — added to `pyproject.toml` for `EmailStr` Pydantic field validation

### Security
- All public form endpoints (`/contact/inquiry`, `/contact/dpa-request`, `/auth/signup`) rate-limited per IP via Redis counters
- Email verification token is HMAC-signed, single-use, 24-hour TTL stored in Redis
- Password hashed with bcrypt; minimum 8 characters enforced by Pydantic and Zod
- No student PII collected or stored in any M2 endpoint — all data is teacher/admin only
- `INTEGRITY_SIMILARITY_THRESHOLD` false positive added to gitleaks allowlist

### Fixed
- Removed conflicting `(public)/signup/page.tsx` stub — real sign-up page lives in `(auth)/signup`
- Added `from __future__ import annotations` to `routers/contact.py`, `services/contact.py`, `services/dpa.py` to resolve `Redis[Any]` FastAPI annotation evaluation error; function signatures use plain `Redis` with `# type: ignore[type-arg]`

### Tests added
- `backend/tests/unit/` — `test_auth_router.py`, `test_auth_router_login.py`, `test_account_router.py`, `test_contact_router.py`, `test_dpa_router.py`, `test_onboarding_router.py` (245 unit tests total)
- `frontend/tests/` — signup form, onboarding wizard, legal DPA form, pricing inquiry form, middleware redirect tests (198 Vitest tests total)

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
