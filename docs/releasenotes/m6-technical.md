# M6 Prioritization & Instruction — Technical Release Notes

**Release**: v0.7.0  
**Milestone**: M6 — Prioritization & Instruction  
**Date**: April 2026  
**PRs**: #197–#212 (16 pull requests)  
**Branch**: `release/m6` → `main`

---

## Database Migrations (Alembic)

All migrations are reversible. Run order is enforced by the revision chain.

| # | Migration | Key change |
|---|---|---|
| 026 | `student_groups_create_table` | New `student_groups` table: `id`, `teacher_id`, `class_id`, `skill_key`, `label`, `student_ids JSONB`, `student_count INT`, `computed_at TIMESTAMPTZ` — RLS-isolated by `teacher_id` |
| 027 | `student_groups_add_stability` | `stability VARCHAR(20)` column (`new`/`persistent`/`exited`) on `student_groups` |
| 028 | `teacher_worklist_items_create_table` | New `teacher_worklist_items` table: `id`, `teacher_id`, `student_id`, `trigger_type`, `skill_key`, `urgency`, `status`, `snoozed_until`, `created_at` — RLS-isolated by `teacher_id` |
| 029 | `instruction_recommendations_create_table` | New `instruction_recommendations` table: `id`, `teacher_id`, `student_id`, `group_id`, `grade_level`, `recommendations JSONB`, `evidence_summary`, `status`, `prompt_version` — RLS-isolated by `teacher_id` |
| 030 | `essay_versions_unique_version_number` | Unique constraint on `(essay_id, version_number)` for `essay_versions`; enables safe resubmission versioning |
| 031 | `revision_comparisons_create_table` | New `revision_comparisons` table: `id`, `essay_id`, `base_version_id`, `revised_version_id`, `criterion_deltas JSONB`, `addressed_feedback JSONB`, `low_effort_flag BOOLEAN`, `created_at` — RLS-isolated via `essay_id → teacher_id` join |
| 032 | `validate_audit_logs_users_fk` | Validates the previously `NOT VALID` foreign key constraint `fk_audit_logs_users` on `audit_logs.user_id → users.id`; no schema change, enforces referential integrity for all existing rows |

**New migration head**: `032_validate_audit_logs_users_fk`  
**Previous head** (M5): `025_essay_versions_signals`

---

## New API Endpoints

### Auto-grouping

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/v1/classes/{classId}/groups` | Current skill-gap groups for the class with student lists and stability |
| `PATCH` | `/api/v1/classes/{classId}/groups/{groupId}` | Manually adjust group membership (add/remove students) |

### Worklist

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/v1/worklist` | Teacher's ranked worklist; optional `?limit=` and filter params |
| `POST` | `/api/v1/worklist/{id}/complete` | Mark a worklist item done |
| `POST` | `/api/v1/worklist/{id}/snooze` | Snooze until next grading cycle |
| `DELETE` | `/api/v1/worklist/{id}` | Permanently dismiss |

### Instruction Recommendations

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/v1/students/{studentId}/recommendations` | Generate recommendation for a student's skill gap |
| `GET` | `/api/v1/students/{studentId}/recommendations` | List all recommendations for a student |
| `POST` | `/api/v1/classes/{classId}/groups/{groupId}/recommendations` | Generate recommendation for a group's shared gap |
| `POST` | `/api/v1/recommendations/{id}/assign` | Teacher assigns exercise (explicit confirmation action) |

### Resubmission Loop

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/v1/essays/{essayId}/resubmit` | Submit revised version; creates new `EssayVersion`, triggers re-grading |
| `GET` | `/api/v1/essays/{essayId}/versions` | All versions with scores and submission metadata |
| `GET` | `/api/v1/essays/{essayId}/revision-comparison` | Score deltas, addressed-feedback flags, and low-effort signal |

---

## New Backend Modules

| Path | Purpose |
|---|---|
| `app/models/revision_comparison.py` | `RevisionComparison` SQLAlchemy model |
| `app/services/auto_grouping.py` | Group clustering from `StudentSkillProfile`; stability tracking; Celery task trigger |
| `app/services/worklist.py` | Worklist item generation (persistence, regression, inconsistency, non-responder triggers); urgency ranking; CRUD operations |
| `app/services/instruction_recommendation.py` | LLM call via `call_instruction`; evidence summary construction; recommendation persistence; assign flow |
| `app/services/resubmission.py` | Resubmission intake and versioning; comparison computation (criterion deltas, addressed-feedback detection, low-effort heuristic) |
| `app/services/essay.py` | Extended: snapshot management, version listing |
| `app/services/grading.py` | Extended: resubmission re-grade path |
| `app/llm/prompts/revision_v1.py` | Versioned prompt for revision comparison LLM call |
| `app/routers/recommendations.py` | Router for all `/recommendations` and `/students/{id}/recommendations` endpoints |
| `app/tasks/auto_grouping.py` | `compute_student_groups` Celery task (triggered after batch grading completes) |
| `app/tasks/worklist.py` | `compute_worklist` Celery task (triggered after group computation) |

---

## New LLM Prompts

| Prompt file | Version key | Purpose |
|---|---|---|
| `app/llm/prompts/revision_v1.py` | `revision-v1` | Detects whether specific feedback points were addressed in a revision; classifies effort level |
| *(instruction prompt)* | `instruction-v1` | Generates mini-lesson / exercise / intervention recommendations per skill dimension |

**Injection defense**: essay content for both prompts is strictly in the `user` role. System prompts contain the standard directive to ignore instructions in submitted text. Revision comparisons receive sanitized diffs, not raw essay content in the system role.

---

## New Frontend Components

| Component | Location | Purpose |
|---|---|---|
| `RecommendationPanel` | `components/recommendations/` | Recommendation card with accept/modify/dismiss controls and assign-exercise confirmation flow |
| `ResubmissionPanel` | `components/grading/` | Side-by-side diff view, score deltas, feedback-addressed indicators, version history list |

### New API client modules

| Module | Endpoints covered |
|---|---|
| `lib/api/recommendations.ts` | Student and group recommendation generation, list, assign |
| `lib/api/resubmission.ts` | Resubmit, version listing, revision comparison |

---

## New Environment Variables

| Variable | Default | Description |
|---|---|---|
| `AUTO_GROUPING_MIN_SIZE` | `2` | Minimum students required to form a skill-gap group |
| `AUTO_GROUPING_SCORE_THRESHOLD` | `0.6` | Normalized skill score below which a student is considered underperforming |
| `RESUBMISSION_LIMIT` | `2` | Max resubmissions per essay (overridable per-assignment via API) |
| `LOW_EFFORT_REVISION_THRESHOLD` | `0.1` | Fraction of content changed below which a revision is flagged as low-effort |
| `INSTRUCTION_PROMPT_VERSION` | `instruction-v1` | Active prompt version written to `instruction_recommendations.prompt_version` |

---

## RLS and Tenant Isolation

All four new tables (`student_groups`, `teacher_worklist_items`, `instruction_recommendations`, `revision_comparisons`) have Row Level Security enabled and policies that restrict access to the owning teacher's rows. The application-layer enforcement uses `teacher_id` in every query — the DB-layer RLS is a defense-in-depth second layer.

Cross-teacher access for all new endpoints is explicitly tested in `tests/integration/test_m6_tenant_isolation.py`.

---

## SOC 2 / FERPA Hardening (PR #214)

Seven compliance fixes applied as part of the M6 security sweep:

| Area | Change |
|---|---||
| Logging | S3 object key values removed from essay-ingestion error logs (FERPA — keys can encode student PII) |
| Error responses | All global exception handlers now return stable, static messages — no `str(exc)` leakage in API responses |
| Auth | Added `RefreshTokenInvalidError`; invalid/expired refresh tokens now return HTTP 401 so the frontend silent-refresh cycle fires correctly |
| Startup guards | Production and staging environments now validate `TRUST_PROXY`, `FRONTEND_URL` (https), and `ALLOW_UNVERIFIED_LOGIN_IN_TEST=false` at startup |
| DB integrity | Migration 032 validates the previously `NOT VALID` `fk_audit_logs_users` FK; referential integrity is now enforced for all existing rows |
| RLS proof | `tests/integration/test_rls_policy_enforcement.py` — non-superuser Postgres role asserts zero rows without tenant context and exactly one row after `SET app.current_teacher_id` |
| CI | Migration chain check is now dynamic (`alembic heads`) — no longer requires a manual revision bump per migration |

---

## Test Coverage

### New backend test files

| File | What it covers |
|---|---|
| `tests/unit/test_auto_grouping_api.py` | Group listing, stability calculation, PATCH membership, tenant isolation |
| `tests/unit/test_worklist_service.py` | Trigger detection (persistence, regression, inconsistency, non-responder), urgency ranking, complete/snooze/dismiss |
| `tests/unit/test_worklist_router.py` | All worklist endpoints, 403 cross-teacher |
| `tests/unit/test_instruction_recommendation_service.py` | LLM mock, evidence summary, recommendation schema validation, assign flow |
| `tests/unit/test_instruction_recommendation_router.py` | Student and group recommendation endpoints, 403 cross-teacher |
| `tests/unit/test_resubmission_service.py` | Version creation, limit enforcement, criterion delta computation, addressed-feedback detection, low-effort flag |
| `tests/unit/test_essay_service.py` | Snapshot management, version listing |
| `tests/unit/test_tenant_isolation.py` | Extended with M6 endpoint coverage |
| `tests/integration/test_m6_tenant_isolation.py` | DB-level RLS assertion on all new tables |
| `tests/integration/test_resubmission.py` | Full resubmission flow against real Postgres (testcontainers) |
| `tests/integration/test_instruction_recommendations.py` | Recommendation generation and listing against real Postgres |

### New frontend test files

| File | What it covers |
|---|---|
| `tests/unit/recommendation-panel.test.tsx` | Recommendation card rendering, accept/dismiss, assign confirmation modal |
| `tests/unit/resubmission-panel.test.tsx` | Diff view rendering, score delta display, version history list |

### New E2E specs

| File | Journey |
|---|---|
| `tests/e2e/mx6b-journey6-worklist-auto-grouping.spec.ts` | Login → class → grade batch → groups tab renders → worklist populated → mark item done |
| `tests/e2e/mx7b-resubmission-loop.spec.ts` | Submit essay → grade → resubmit → comparison view → score delta visible |

---

## Upgrade Notes

1. **Run migrations**: `alembic upgrade head` — applies migrations 026 through 032
2. **Add new env vars** to `.env` / Railway / secrets store (all have safe defaults — no hard requirement at startup)
3. **Rebuild Docker images**: `docker compose build backend worker` — new Celery tasks require updated worker image
4. **No breaking changes** to any existing API endpoints; all additions are new routes or additive fields
