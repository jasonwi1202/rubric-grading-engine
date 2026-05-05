# M8 Polish & Hardening — Technical Release Notes

**Release**: v0.9.0  
**Milestone**: M8 — Polish & Hardening  
**Date**: May 2026  
**PRs**: #237–#241 (feature delivery), #244, #249–#252 (quality & release finalization)  
**Branch**: `release/m8` → `main`

---

## Database Migrations (Alembic)

No new migrations in M8. All 33 existing revisions were audited for zero-downtime patterns, reversibility, data safety, and idempotency (PR #250). Rollback paths verified for every revision.

**Current migration head**: `033_intervention_recommendations` (unchanged from M7)

---

## New API Endpoints

### Debug / test-mode endpoints (gated by `TESTING_MODE=true`)

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/v1/debug/export-task/arm-failure` | Arms a one-shot deterministic failure on the next export Celery task execution |
| `POST` | `/api/v1/debug/short-lived-token` | Issues an access token with a sub-30-second TTL for E2E silent-refresh testing |

Both endpoints return `404` when `TESTING_MODE` is not set. They must never be reachable in production.

---

## New Frontend Modules

| Path | Purpose |
|---|---|
| `components/layout/DashboardSidebar.tsx` | Persistent sidebar with collapsible class accordion, sign-out, and `InterventionBadge` count; mobile drawer variant with focus trap and Escape key |
| `components/layout/Breadcrumbs.tsx` | Auto-generated breadcrumb trail from pathname + React Query cache; supports all dashboard route shapes; no extra API calls |
| `components/classes/LessonPlanningPanel.tsx` | Lesson planning tab on class detail page; wraps instruction recommendations API with generate / accept / dismiss controls |

---

## Modified Frontend Modules

| Path | Key changes |
|---|---|
| `app/(dashboard)/layout.tsx` | Replaced inline nav with `DashboardSidebar`; added `<Breadcrumbs>` below top bar |
| `app/(dashboard)/dashboard/page.tsx` | Sidebar-aware layout; no functional change to worklist content |
| `app/(dashboard)/dashboard/classes/[classId]/page.tsx` | Added "Lesson Planning" tab; Groups tab layout updated for sidebar width |
| `app/(dashboard)/dashboard/assignments/[assignmentId]/review/[essayId]/page.tsx` | Layout padding adjusted for sidebar; `TextCommentBankPicker` wired into criterion feedback editors |
| `app/(dashboard)/dashboard/interventions/page.tsx` | New `/dashboard/interventions` page: list, filter by status, approve with note, dismiss |
| `app/(dashboard)/dashboard/copilot/page.tsx` | Minor layout update for sidebar integration |
| `components/worklist/WorklistPanel.tsx` | Urgency tier indicators (Critical/High/Medium); corrected top-10 collapse logic |
| `components/grading/ReviewQueue.tsx` | Layout alignment corrections for sidebar-integrated view |

---

## Backend Changes

### New config flags

| Flag | Type | Default | Purpose |
|---|---|---|---|
| `TESTING_MODE` | `bool` | `false` | Gates all `/debug/*` endpoints. Must be `false` in production. |
| `EXPORT_TASK_FORCE_FAIL` | `bool` | `false` | Arms the next export task to fail deterministically. Only effective when `TESTING_MODE=true`. |

### Modified backend modules

| Path | Change |
|---|---|
| `app/config.py` | Added `testing_mode` and `export_task_force_fail` settings |
| `app/routers/debug.py` | New router; mounts only when `settings.testing_mode` is `True` |
| `app/tasks/export.py` | Reads `EXPORT_TASK_FORCE_FAIL` at task execution time; raises `RuntimeError` and clears flag if armed |

---

## Test Changes

### Backend unit tests

| File | Change |
|---|---|
| `tests/unit/test_auth_service.py` | `autouse` fixture pins `rate_limit_enabled=True`, `allow_unverified_login_in_test=False` |
| `tests/unit/test_auth_service_jwt.py` | `autouse` fixture pins `allow_unverified_login_in_test=False` |
| `tests/unit/test_config.py` | Env-isolation fixture; added coverage for new `testing_mode` and `export_task_force_fail` fields |
| `tests/unit/test_dependencies.py` | `autouse` fixture pins `allow_unverified_login_in_test=False` |
| `tests/unit/test_export_task.py` | Added failure-injection coverage; removed stale mock patterns |
| `tests/unit/test_security_middleware.py` | `autouse` fixture pins `rate_limit_enabled=True`, `trust_proxy_headers=False` |

### Backend integration tests

| File | Change |
|---|---|
| `tests/integration/test_migration_roundtrip.py` | Verified all 33 revisions upgrade/downgrade cleanly |

### Frontend unit tests

| File | Change |
|---|---|
| `tests/unit/worklist-panel.test.tsx` | Added urgency tier, snooze, and dismiss coverage |
| `tests/unit/review-queue.test.tsx` | Added sidebar-layout rendering assertions |
| `tests/unit/text-comment-bank-picker.test.tsx` | Full save / search / apply lifecycle (28 tests) |

### Frontend E2E (Playwright)

New spec files added (tests marked `skip` until `TESTING_MODE=true` is wired into CI):

| File | Coverage |
|---|---|
| `tests/e2e/mx8-journey10-coverage-hardening.spec.ts` | Interventions lifecycle, export failure + retry, class insights, upload negatives, teacher notes persistence |
| `tests/e2e/mx4-accessibility.spec.ts` | Dashboard overview and essay review panel a11y assertions |

Modified:

| File | Change |
|---|---|
| `tests/e2e/mx3-journeys.stub.spec.ts` | Journey 1 class-name assertion scoped to `<main>` to avoid strict-mode ambiguity with sidebar link |

---

## Breaking Changes

None. This milestone contains no API changes, schema changes, or behavioral changes to existing endpoints.

---

## Upgrade Notes

No manual steps required. No new environment variables are mandatory. `TESTING_MODE` and `EXPORT_TASK_FORCE_FAIL` default to `false` and are safe to omit in production.

---

## Security Review

Per the M8.9 security pass (PR #251):

- All error log calls use `error_type=type(exc).__name__` only — no `str(exc)` in log output
- All API error responses return static message strings — no exception message forwarded to client
- All new UI surfaces enforce `grade.is_locked` read-only state
- All new routes are behind `get_current_teacher` dependency
- Debug endpoints are permanently unavailable when `TESTING_MODE` is not set
- No student PII in any log line, URL parameter, or browser storage introduced in M8
- No hardcoded secrets, API keys, or credential-format strings in any file added or modified in this release
- Gitleaks scan: clean
