# M2 Release Notes — Technical Reference

**Version:** v0.3.0  
**Milestone:** M2 — Public Website & Onboarding  
**Branch:** `release/m2`  
**PRs merged:** #40 (M2.1) · #41 (M2.2) · #42 (M2.3) · #43 (M2.4) · #44 (M2.5) · #45 (M2.6) · #46 (M2.7) · #47 (M2.8) · #48 (M2.9) · #49 (M2.10)

---

## New Backend Endpoints

| Method | Path | Auth | Description |
|---|---|---|---|
| `POST` | `/api/v1/auth/signup` | Public | Create teacher account; bcrypt password; enqueue verification email; 201 |
| `GET` | `/api/v1/auth/verify-email` | Public | Verify HMAC-signed token; mark `users.email_verified`; Redis single-use TTL |
| `POST` | `/api/v1/auth/resend-verification` | Public | Re-send verification email (max 3/hour/email) |
| `GET` | `/api/v1/onboarding/status` | JWT | Returns `{ step, completed }` based on teacher's class/rubric/onboarding state |
| `POST` | `/api/v1/onboarding/complete` | JWT | Sets `users.onboarding_complete = true`; audit log entry |
| `GET` | `/api/v1/account/trial` | JWT | Returns `{ trial_ends_at, days_remaining, is_expired }` |
| `POST` | `/api/v1/contact/inquiry` | Public | Store school/district inquiry; Redis rate-limit 5/IP/hour; Celery notification email |
| `POST` | `/api/v1/contact/dpa-request` | Public | Store DPA request; Redis rate-limit 3/IP/hour; Celery notification email |

---

## New Celery Tasks

| Task | Module | Trigger |
|---|---|---|
| `send_verification_email` | `app.tasks.email` | On `POST /auth/signup` and `POST /auth/resend-verification` |
| `send_welcome_email` | `app.tasks.email` | On `GET /auth/verify-email` (post-verification) |
| `send_trial_expiry_warning` | `app.tasks.email` | Celery Beat: daily scan at 7 days and 1 day remaining |
| `send_trial_expired` | `app.tasks.email` | Celery Beat: daily scan at 0 days remaining |
| `send_inquiry_notification` | `app.tasks.email` | On `POST /contact/inquiry` |
| `send_dpa_notification` | `app.tasks.email` | On `POST /contact/dpa-request` |
| `scan_trial_expirations` | `app.tasks.email` | Celery Beat: daily at 00:00 UTC |

---

## New Database Models

| Model | Table | Notes |
|---|---|---|
| `ContactInquiry` | `contact_inquiries` | School/district purchase inquiries; no student PII |
| `DpaRequest` | `dpa_requests` | DPA requests from `/legal/dpa`; no student PII |
| `users` columns added | `users` | `email_verified`, `onboarding_complete`, `trial_ends_at`, `unsubscribe_token` |

> **Note:** M2 models and column additions are applied via Alembic migrations included in the constituent PRs. Run `alembic upgrade head` after deploying.

---

## New Frontend Routes

| Route | Group | Description |
|---|---|---|
| `/` | `(public)` | Landing page — static |
| `/product` | `(public)` | Product deep-dive — static |
| `/how-it-works` | `(public)` | Workflow walkthrough — static |
| `/about` | `(public)` | About page — static |
| `/pricing` | `(public)` | Pricing + inquiry form |
| `/ai` | `(public)` | AI transparency — static |
| `/legal/*` | `(public)` | 5 legal pages + DPA request form |
| `/signup` | `(auth)` | Teacher registration form |
| `/signup/verify` | `(auth)` | "Check your email" holding page |
| `/auth/verify` | `(auth)` | Email verification link handler |
| `/onboarding` | `(onboarding)` | Wizard entry — step routing |
| `/onboarding/class` | `(onboarding)` | Step 1: Create first class |
| `/onboarding/rubric` | `(onboarding)` | Step 2: Build first rubric |
| `/onboarding/done` | `(onboarding)` | Completion page |

---

## New Environment Variables

| Variable | Default | Description |
|---|---|---|
| `SMTP_HOST` | `localhost` | SMTP server hostname |
| `SMTP_PORT` | `1025` | SMTP server port (1025 = Mailpit in Docker Compose) |
| `SMTP_USERNAME` | `` | SMTP auth username (empty = no auth) |
| `SMTP_PASSWORD` | `` | SMTP auth password |
| `SMTP_FROM_EMAIL` | `noreply@example.com` | Sender address for all system emails |
| `SMTP_TLS` | `false` | Enable STARTTLS for SMTP |
| `CONTACT_EMAIL` | `hello@example.com` | Team inbox for inquiry and DPA notifications |
| `HMAC_SECRET_KEY` | *(required)* | HMAC key for email verification and unsubscribe tokens |
| `TRIAL_DURATION_DAYS` | `30` | Trial length in days from account creation |
| `INTEGRITY_SIMILARITY_THRESHOLD` | `0.25` | Similarity threshold for future integrity checks (M4) |

---

## Dependency Changes

| Package | Change | Reason |
|---|---|---|
| `email-validator>=2.1.0` | Added (backend) | Required by Pydantic `EmailStr` field validation |

---

## Pre-existing Errors Fixed

| Error | Root cause | Fix |
|---|---|---|
| Route conflict: two pages resolve to `/signup` | `(public)/signup/page.tsx` stub from M2.1 not removed when `(auth)/signup/page.tsx` was added in M2.8 | Deleted the stub |
| `mypy` errors in `routers/contact.py`, `services/contact.py`, `services/dpa.py` | `Redis` type annotations missing `[Any]` type args; `aclose` not in stubs | Added `from __future__ import annotations`; function signatures use plain `Redis` with `# type: ignore[type-arg]`; `aclose()` suppressed with `# type: ignore[attr-defined]` |
| `email-validator` not installed | Missing from `pyproject.toml` | Added `email-validator>=2.1.0` |
| Gitleaks false positive: `INTEGRITY_SIMILARITY_THRESHOLD` | Key name matched generic-api-key pattern | Added regex to `.gitleaks.toml` allowlist |

---

## Deferred Items

| Item | Reason | Target |
|---|---|---|
| Payment/checkout flow | Requires Stripe or equivalent integration; not required for trial onboarding | Post-M3 |
| Attorney-approved legal text | All legal pages carry `[ATTORNEY DRAFT REQUIRED]` — requires external counsel | Before production launch |
| Upgrade path enforcement | Tiered access control requires billing state in user model | Post-M3 |
| Email delivery in production | SMTP configured for local Mailpit; production SMTP (`SMTP_HOST`, `SMTP_USERNAME`, `SMTP_PASSWORD`) must be configured before launch | Ops/deployment |

---

## Test Coverage

| Suite | Count | Notes |
|---|---|---|
| Backend unit tests | 245 | All passing; covers all new routers, services, and Celery task logic |
| Frontend Vitest | 198 | All passing; covers signup form, onboarding wizard, legal forms, middleware redirects |
| Backend integration | 6 | S3/MinIO testcontainer; passes locally with Docker |

---

## Post-Merge Steps

1. Merge PR to `main` (squash or merge commit — no rebase)
2. Tag `main` as `v0.3.0`
3. Move `[Unreleased]` M2 block in `CHANGELOG.md` to `[v0.3.0]` with today's date
4. Close the [M2 GitHub milestone](https://github.com/jasonwi1202/rubric-grading-engine/milestone/2)
5. Set `HMAC_SECRET_KEY`, `SMTP_*`, and `CONTACT_EMAIL` in the deployment environment before any real traffic
