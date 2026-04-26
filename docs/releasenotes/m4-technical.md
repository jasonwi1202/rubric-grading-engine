# M4 Workflow — Technical Release Notes

**Release**: v0.5.0  
**Milestone**: M4 — Workflow  
**Date**: April 2026  
**PRs**: #132–#151 (20 pull requests)  
**Branch**: `release/m4` → `main`

---

## Database Migrations (Alembic)

All migrations are reversible. Run order is enforced by the revision chain.

| # | Migration | Key change |
|---|---|---|
| 012 | `confidence_add_overall_confidence_to_grades` | `confidence VARCHAR(10)` on `criterion_scores`; `overall_confidence VARCHAR(10)` on `grades` |
| 013 | `integrity_report_create_integrity_reports_table` | New table with `essay_version_id`, `teacher_id`, `provider`, `ai_likelihood`, `similarity_score`, `flagged_passages JSONB`, `status` enum |
| 014 | `essay_embedding_add_embedding_to_essay_versions` | `embedding vector(1536)` on `essay_versions` (pgvector) |
| 015 | `integrity_report_add_unique_constraint_version_provider` | Unique constraint: `(essay_version_id, provider)` |
| 016 | `integrity_report_add_reviewed_at` | `reviewed_at TIMESTAMPTZ` on `integrity_reports` |
| 017 | `regrade_request_create_regrade_requests_table` | New table with `grade_id`, `criterion_score_id` (nullable FK), `teacher_id`, `dispute_text`, `status` enum, `resolution_note`, `resolved_at` |
| 018 | `media_comment_create_media_comments_table` | New table with `grade_id`, `teacher_id`, `s3_key`, `duration_seconds`, `mime_type`, `is_banked` |
| 019 | `media_comment_add_is_banked` | `is_banked BOOLEAN NOT NULL DEFAULT false` (backfill-safe) |
| 020 | `rls_enable_tenant_isolation` | `ALTER TABLE … ENABLE ROW LEVEL SECURITY` + `CREATE POLICY` on all tenant-scoped tables |
| 021 | `grades_add_prompt_version_default` | `prompt_version VARCHAR(20) NOT NULL DEFAULT 'v1'` on `grades` |

---

## New API Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/v1/essays/{id}/integrity` | Latest `IntegrityReport` for essay; 404 if none |
| `PATCH` | `/api/v1/integrity-reports/{id}/status` | Teacher sets `reviewed_clear` or `flagged` |
| `POST` | `/api/v1/grades/{id}/regrade-requests` | Submit regrade request (window + limit enforced) |
| `GET` | `/api/v1/assignments/{id}/regrade-requests` | List open regrade requests for assignment |
| `POST` | `/api/v1/regrade-requests/{id}/resolve` | Approve (optional new score) or deny (required note); audit-logged |
| `POST` | `/api/v1/grades/{id}/media-comments` | Create media comment record after S3 upload |
| `GET` | `/api/v1/media-comments/{id}/url` | Pre-signed S3 URL for playback (teacher-scoped) |
| `DELETE` | `/api/v1/media-comments/{id}` | Remove record and S3 object |
| `POST` | `/api/v1/media-comments/{id}/save-to-bank` | Mark comment as reusable |

### Updated endpoints
- `GET /api/v1/essays/{id}/grade` — response now includes `confidence`, `overall_confidence`, `prompt_version`
- `GET /api/v1/health` — returns dependency status for DB, Redis, S3 (not just 200 OK)

---

## New Backend Modules

| Path | Purpose |
|---|---|
| `app/middleware.py` | `SecurityHeadersMiddleware`, `RateLimitMiddleware`, `CorrelationIdMiddleware` |
| `app/logging_config.py` | Structured JSON logging with correlation ID injection |
| `app/models/integrity_report.py` | `IntegrityReport` SQLAlchemy model |
| `app/models/regrade_request.py` | `RegradeRequest` SQLAlchemy model |
| `app/models/media_comment.py` | `MediaComment` SQLAlchemy model |
| `app/routers/integrity.py` | Integrity report router |
| `app/routers/regrade_requests.py` | Regrade request router |
| `app/routers/media_comments.py` | Media comment router |
| `app/schemas/integrity.py` | Pydantic schemas for integrity responses |
| `app/schemas/regrade_request.py` | Pydantic schemas for regrade request create/resolve |
| `app/schemas/media_comment.py` | Pydantic schemas for media comment |
| `app/services/embedding.py` | Essay embedding computation and similarity query |
| `app/services/integrity.py` | `IntegrityProvider` abstract class, `InternalProvider`, `OriginalityAiProvider` |
| `app/services/regrade_request.py` | Window enforcement, limit enforcement, resolve logic |
| `app/services/media_comment.py` | S3 upload coordination, pre-signed URL generation |
| `app/tasks/embedding.py` | `compute_essay_embedding` Celery task |

---

## New Frontend Modules

| Path | Purpose |
|---|---|
| `components/grading/IntegrityPanel.tsx` | AI likelihood indicator, similarity score, flagged passages |
| `components/grading/RegradeQueue.tsx` | Queue tab, log form, side-by-side review panel |
| `components/grading/AudioRecorder.tsx` | MediaRecorder API wrapper, 3-min limit, S3 upload |
| `components/grading/VideoRecorder.tsx` | getUserMedia + optional getDisplayMedia, same upload flow |
| `components/grading/MediaBankPicker.tsx` | Saved comment bank picker and apply action |
| `lib/api/integrity.ts` | API client functions for integrity endpoints |
| `lib/api/regrade-requests.ts` | API client functions for regrade endpoints |
| `lib/api/media-comments.ts` | API client functions for media comment endpoints |
| `lib/rubric/parseRubricSnapshot.ts` | Shared rubric snapshot parser used by review components |

---

## Security Changes

- **`SecurityHeadersMiddleware`**: `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Strict-Transport-Security: max-age=31536000; includeSubDomains`, `X-XSS-Protection: 1; mode=block` on every response
- **`RateLimitMiddleware`**: Redis INCR/EXPIRE counters keyed `ratelimit:{METHOD}:{PATH}:{client_ip}`. Rules: signup 5/hr, login 10/15 min, refresh 30/hr. Fails open if Redis unavailable (logged at ERROR)
- **`CORS_ORIGINS` validator**: wildcard `*` raises `ValueError` at startup, preventing misconfiguration
- **RLS migration (020)**: all tenant-scoped tables now have `ENABLE ROW LEVEL SECURITY` + policies at the PostgreSQL layer, in addition to existing service-layer `teacher_id` filters
- **S3 key format for media**: `media/{teacher_id}/{grade_id}/{uuid}.{ext}` — no student PII in key
- **Integrity language**: all UI copy uses "potential similarity detected" framing; no automated conclusions
- **`prompt_version` on Grade**: every grade now records which prompt template produced it, enabling future rollback analysis

---

## Observability Changes

- **Correlation IDs** (`CorrelationIdMiddleware`): `X-Request-ID` header read or generated per request; propagated to all Celery task kwargs; every log line in the request lifecycle carries it
- **Structured logging** (`logging_config.py`): JSON formatter with fixed fields: `timestamp`, `level`, `logger`, `service`, `correlation_id`, message; entity IDs bound via `extra={}` — never student names or essay content
- **Health check** (`GET /api/v1/health`): now returns `{"db": "ok|error", "redis": "ok|error", "s3": "ok|error"}` instead of a bare 200

---

## CI Changes

- `pip-audit` step added: fails build on high/critical CVEs in Python dependencies
- `npm audit` step added: fails build on high/critical CVEs in Node dependencies
- `@axe-core/playwright` accessibility scan added to E2E job: fails on any critical accessibility violation
- E2E job now runs four Playwright journeys against Docker Compose stack with mocked LLM

---

## Test Coverage Added

**Backend** (1187 total, all passing):
- `test_confidence_schema.py` — schema validation, derivation
- `test_integrity_report_model.py` — model and relationship
- `test_embedding_task.py` — task execution (OpenAI mocked)
- `test_integrity_service.py` — provider selection, fallback, mocked third-party client
- `test_integrity_router.py` — tenant isolation (cross-teacher 403)
- `test_regrade_request_model.py` — model, FK relationships
- `test_regrade_request_service.py` — window enforcement, limit enforcement, resolve happy path, deny requires note
- `test_regrade_request_router.py` — tenant isolation
- `test_security_middleware.py` — header assertions (Redis mocked for rate limiter)
- `test_tenant_isolation.py` — cross-teacher 403 on all major resource types
- `test_logging_config.py` — no-PII assertion on structured log output

**Frontend** (539 total, all passing):
- `review-queue.test.tsx` (extended) — confidence badge, sort, filter, bulk-approve
- `integrity-panel.test.tsx` — render, status actions
- `regrade-queue.test.tsx` — queue render, approve, deny-blocked-without-note
- `audio-recorder.test.tsx` — toggle, upload, delete, playback
- `video-recorder.test.tsx` — MIME type, screen share, permission denied
- `media-bank-picker.test.tsx` — bank picker, apply

**E2E** (4 journeys):
- Journey 1: login → class → students → rubric → assignment
- Journey 2: upload → auto-assign → batch grade → progress
- Journey 3: review → override score → edit feedback → lock grade *(HITL guarantee)*
- Journey 4: export PDF ZIP + CSV download

---

## Pre-existing Bug Fixes

- **Auth router rate-limit collision in tests**: `TestSignupValidation` class exhausted the 5/hr signup rate limit across test runs because all 8 tests POST to `/auth/signup` from the same testclient IP using a shared Redis client. Fixed by adding an `autouse` monkeypatch fixture in `test_auth_router.py` that sets `app.middleware._RATE_LIMIT_RULES = []` for the duration of auth router tests. The service-layer rate limit behavior (tested in `test_auth_service.py`) is unaffected.
- **UTF-16 BOM on two onboarding files**: `frontend/app/(onboarding)/onboarding/class/page.tsx` and `frontend/tests/unit/onboarding-class-page.test.tsx` were written as UTF-16 LE during a prior merge conflict resolution using PowerShell `>` redirect. oxc rejected them as binary. Both re-encoded as UTF-8 without BOM.

---

## New Environment Variables

| Variable | Default | Description |
|---|---|---|
| `INTEGRITY_PROVIDER` | `internal` | Active integrity provider: `internal` or `originality_ai` / `winston_ai` |
| `INTEGRITY_API_KEY` | — | API key for third-party integrity provider |
| `INTEGRITY_SIMILARITY_THRESHOLD` | `0.85` | Cosine similarity threshold (0.0–1.0) for flagging essay pairs |
| `REGRADE_WINDOW_DAYS` | `7` | Days after grade creation within which regrade requests may be submitted |
| `REGRADE_MAX_PER_GRADE` | `1` | Maximum regrade requests per grade |
| `S3_PRESIGNED_URL_EXPIRE_SECONDS` | `3600` | Lifetime of pre-signed media comment playback URLs |
| `GRADING_PROMPT_VERSION` | `v1` | Prompt version string written to `grades.prompt_version` at grade-write time |

---

## Upgrade Notes

1. Run `alembic upgrade head` — 10 new migrations (012–021). Migration 020 (RLS) takes a brief exclusive lock on all tenant tables; run during a maintenance window or off-peak for production.
2. pgvector extension must be enabled before running migration 014: `CREATE EXTENSION IF NOT EXISTS vector;`
3. Set `INTEGRITY_PROVIDER`, `INTEGRITY_API_KEY`, and `INTEGRITY_SIMILARITY_THRESHOLD` in your environment if using third-party integrity checking.
4. Set `GRADING_PROMPT_VERSION=v2` when deploying the updated grading prompt (confidence scoring output).
