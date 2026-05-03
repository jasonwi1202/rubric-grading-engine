# M7 Closed Loop — Technical Release Notes

**Release**: v0.8.0  
**Milestone**: M7 — Closed Loop  
**Date**: May 2026  
**PRs**: #221–#224 (feature delivery), #225 (release finalization)  
**Branch**: `release/m7` → `main`

---

## Database Migrations (Alembic)

| # | Migration | Key change |
|---|---|---|
| 033 | `intervention_recommendations_create_table` | New `intervention_recommendations` table with `teacher_id`, `student_id`, `trigger_type`, `skill_key`, `urgency`, `trigger_reason`, `evidence_summary`, `suggested_action`, `details JSONB`, `status`, `actioned_at`, `created_at`; RLS-isolated by `teacher_id`; partial unique index prevents duplicate pending signals |

**New migration head**: `033_intervention_recommendations`  
**Previous head** (M6): `032_validate_audit_logs_users_fk`

---

## New API Endpoints

### Intervention recommendations

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/v1/interventions` | List intervention recommendations for the authenticated teacher |
| `POST` | `/api/v1/interventions/{id}/approve` | Approve a pending intervention recommendation |
| `DELETE` | `/api/v1/interventions/{id}` | Dismiss a pending intervention recommendation |

### Teacher copilot

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/v1/copilot/query` | Answer a teacher's natural-language question using live class data |

### Worklist additions

| Area | Change |
|---|---|
| `teacher_worklist_items.trigger_type` | Added support for `trajectory_risk` in service/schema handling |
| Worklist details payload | Predictive items include `is_predictive`, `confidence_level`, `consecutive_decline_count`, `total_decline`, `recent_scores` |

---

## New Backend Modules

| Path | Purpose |
|---|---|
| `app/models/intervention_recommendation.py` | SQLAlchemy model for agent-generated intervention recommendations |
| `app/services/intervention_agent.py` | Signal detection, intervention recommendation generation, list/approve/dismiss service logic |
| `app/routers/intervention.py` | Intervention recommendation API router |
| `app/tasks/intervention.py` | Scheduled intervention scan task |
| `app/schemas/intervention.py` | Intervention request/response schemas |
| `app/services/copilot.py` | Teacher-scoped Postgres context assembly for copilot queries |
| `app/routers/copilot.py` | Copilot query API router |
| `app/schemas/copilot.py` | Copilot request/response schemas |
| `app/llm/prompts/copilot_v1.py` | Versioned teacher-copilot system prompt |

---

## LLM / Prompt Infrastructure

| Prompt file | Version key | Purpose |
|---|---|---|
| `app/llm/prompts/copilot_v1.py` | `copilot-v1` | Teacher-scoped natural-language query answering over class profile and worklist data |

### Copilot response validation

- Raw LLM output is parsed by `parse_copilot_response()` in `app/llm/parsers.py`
- Unknown `response_type` values normalize to `ranked_list`
- Ranked item `value` fields clamp to `[0.0, 1.0]`
- Blank/missing strings fall back to safe placeholders
- Response parsing retries once with a corrective prompt on JSON failure

### Prompt injection / FERPA controls

- No essay content is sent to the copilot prompt
- No student names are included in the LLM context — only UUIDs and aggregate data
- The system prompt instructs the model to ignore directives found in the class data
- Names are resolved after parsing from the database using authenticated `teacher_id`

---

## Frontend Additions

| Path | Purpose |
|---|---|
| `app/(dashboard)/dashboard/copilot/page.tsx` | Dedicated teacher copilot page |
| `components/copilot/CopilotPanel.tsx` | Conversational copilot UI with class scoping, history, uncertainty display, and structured ranked response rendering |
| `lib/api/copilot.ts` | Typed API client wrapper for `POST /copilot/query` |

### Frontend behavior notes

- Query input constraints match backend schema: non-blank, max 500 chars
- Empty class selector values normalize to `null` before API submission
- Errors map to static safe UI strings rather than rendering raw server messages
- Student profile links use UUID-only URLs
- Link `aria-label` values are generic and do not include student display names

---

## Demo / Local Validation Updates

| Area | Change |
|---|---|
| `docker-compose.demo.yml` | Demo stack now advertises M7 coverage and enables `LLM_FAKE_MODE=true` |
| `backend/scripts/seed_demo_data.py` | Seeds one `trajectory_risk` worklist item and one pending intervention recommendation |
| `scripts/smoke_test_demo.py` | Adds authenticated M7 checks for predictive worklist data, interventions, and copilot query responses |
| `DEMO.md` | Adds M7 walkthrough steps and explains deterministic fake-LLM demo mode |

---

## Test Coverage

### New backend test files

| File | What it covers |
|---|---|
| `tests/unit/test_intervention_agent_service.py` | Signal detection, deduplication, list/approve/dismiss service logic |
| `tests/unit/test_intervention_router.py` | Intervention endpoint envelope, auth, error mapping |
| `tests/unit/test_intervention_task.py` | Scheduled task registration and service invocation |
| `tests/unit/test_copilot_service.py` | Teacher-scoped class/profile/worklist loading, name resolution, response shaping |
| `tests/unit/test_copilot_router.py` | Copilot endpoint auth, validation, and error mapping |
| `tests/unit/test_llm_parsers.py` | Copilot parser normalization and fallback coverage |
| `tests/integration/test_interventions.py` | Real Postgres intervention flow and tenant isolation |
| `tests/integration/test_copilot.py` | Real Postgres copilot endpoint integration and class scoping |

### New frontend test files

| File | What it covers |
|---|---|
| `tests/unit/copilot-panel.test.tsx` | Copilot panel rendering, validation, error states, class scope payload normalization |

### E2E coverage

| File | Journey |
|---|---|
| `tests/e2e/mx7-journey9-copilot.spec.ts` | Login → navigate to copilot → ask question → receive structured read-only response |
| `tests/e2e/mx3-journeys.stub.spec.ts` | Hardened to avoid strict-mode violation on duplicate Upload essays buttons |
| `tests/e2e/m4-workflows.spec.ts` | Hardened login flow by waiting for hydration/network idle before sign-in interaction |

---

## Upgrade Notes

1. Run migrations: `alembic upgrade head` — applies migration 033
2. Rebuild backend and worker images — new router, task, and prompt modules are included in M7
3. No breaking API changes to existing M6 routes; M7 is additive
4. Demo users can exercise M7 without any OpenAI key because demo compose enables deterministic fake LLM mode