---
applyTo: "backend/**"
---

# Backend Engineer Review Instructions

When reviewing a PR that touches `backend/**`, check every item below.

## API Conformance

- [ ] All new or modified endpoints are under `/api/v1/` — no unversioned routes
- [ ] Request and response bodies match the Pydantic schemas in `backend/app/schemas/` exactly
- [ ] Error responses use the structured format: `{"error": {"code": "...", "message": "...", "field": "..."}}`
- [ ] New endpoints have corresponding entries reflected in `docs/architecture/api-design.md`
- [ ] **All endpoints return the `{"data": ...}` response envelope** — never return a bare JSON object or bare list. A bare response causes `apiGet()` / `apiPost()` in the frontend client to silently return `undefined`. Use `JSONResponse(content={"data": ...})` or the project's `DataResponse` wrapper consistently.
- [ ] **`IntegrityError` is caught at every `db.commit()` that could hit a uniqueness constraint** — wrap in try/except, rollback, and re-raise as `ConflictError`. An unhandled `IntegrityError` from a concurrent request returns a generic 500 to the client.
- [ ] **Uploaded filenames are never embedded raw in S3 keys or error messages** — sanitize/normalize filenames before constructing S3 object keys, and never echo `upload.filename` in exception messages (FERPA: filenames can contain student PII).

## Authentication & Authorization

- [ ] Every endpoint that touches teacher data has `teacher: User = Depends(get_current_teacher)`
- [ ] The authenticated `teacher.id` is used to scope all queries — never trust a client-supplied teacher ID
- [ ] No endpoint returns data belonging to a different teacher (see tenant isolation section)

## Multi-Tenant Data Isolation

Every query touching classes, students, assignments, essays, grades, or rubrics must be scoped to the authenticated teacher. This is a hard block if violated.

- [ ] All service functions accept `teacher_id` as an explicit parameter
- [ ] Every database query includes `WHERE teacher_id = :teacher_id` or an equivalent join that enforces teacher ownership
- [ ] **No two-query ownership pattern** — do NOT do a `teacher_id` check in one query and then fetch data in a second query that omits `teacher_id`. Both the ownership check and the data fetch must be in a single query, or the data fetch must independently include `teacher_id`. A check-then-fetch pattern without scoping the data query is a tenant isolation gap even if the check passes.
- [ ] Celery tasks include `teacher_id` in their payload and validate ownership before loading any entity
- [ ] Cross-teacher access attempts return `403` — do not return `404` in ways that leak existence
- [ ] RLS policy on the table is set for all tenant-scoped entities (see `docs/architecture/security.md#2-multi-tenant-data-isolation`)

## Prompt Injection Defense

Any code path that sends essay content to the LLM must follow these rules — no exceptions:

- [ ] Essay content is always in the **`user` role** — never in the system prompt
- [ ] The system prompt explicitly instructs the model to ignore directives found in the essay
- [ ] Essay text is wrapped in explicit delimiters (`<ESSAY_START>` / `<ESSAY_END>`) in the user turn
- [ ] LLM responses are validated against the grading schema before any data is written to the database
- [ ] Score values are range-clamped server-side regardless of what the LLM returns

Reference: `docs/architecture/security.md#1-prompt-injection-defense`

## FERPA / Student Data

- [ ] No student PII (name, essay content, grades) in any log statement — use entity IDs only
- [ ] Essay content is never logged at any level in production code paths
- [ ] No student data is sent to third-party services not covered by a DPA
- [ ] Student data is never used for LLM fine-tuning or model training

Reference: `docs/architecture/security.md#5-ferpa-compliance`

## Audit Log

Every endpoint that changes grade state or performs a consequential access/admin action must write an audit log entry. See the full action catalog in `docs/architecture/data-model.md#auditlog`.

**Grade events** (every change to grade state):
- [ ] `score_override` on any criterion score change
- [ ] `feedback_edited` on any feedback text change
- [ ] `grade_locked` when a grade is locked
- [ ] `score_clamped` when the LLM returns an out-of-range score that is clamped
- [ ] `regrade_resolved` on regrade request resolution
- [ ] Audit entries include `before_value` and `after_value` as JSONB

**Auth events** (required for SOC 2 CC6):
- [ ] `login_success` and `login_failure` on every auth attempt — include `ip_address`
- [ ] `logout` on explicit logout
- [ ] `token_refreshed` on every refresh token use

**Data access events** (required for SOC 2 + FERPA):
- [ ] `export_requested` and `export_downloaded` on all export operations
- [ ] `student_data_deletion_requested` and `student_data_deletion_completed` on FERPA deletion requests

**Audit table rules:**
- [ ] Audit table is INSERT-only — no UPDATE or DELETE on `audit_logs` anywhere in the codebase
- [ ] `teacher_id` is nullable — system-generated events (e.g., `score_clamped`) may have no acting teacher

Reference: `docs/architecture/data-model.md#auditlog`, `docs/architecture/security.md#6-soc-2-readiness`

## Rubric Snapshot Rule

- [ ] Grading always uses `assignment.rubric_snapshot` — never the live `Rubric` record
- [ ] No code path queries the live `Rubric` during grading or validation of graded results
- [ ] Rubric snapshot is written at assignment creation time and never mutated afterward

Reference: `docs/architecture/data-model.md#key-design-decisions`

## Code Quality

- [ ] All public functions have type annotations (`mypy` strict)
- [ ] `ruff check .` passes with zero errors from `backend/`
- [ ] `ruff format --check .` passes with zero "would reformat" files from `backend/`
- [ ] No `# type: ignore` without an inline explanation
- [ ] SQLAlchemy queries use `AsyncSession` — no synchronous DB calls in async endpoints
- [ ] **`db.add()` and `db.delete()` are synchronous** — do NOT `await` them. Only `db.flush()`, `db.commit()`, `db.refresh()`, and `db.execute()` are awaitable. Awaiting a synchronous method silently awaits `None` in production and causes `AsyncMock` mismatches in tests.
- [ ] No `SELECT *` — always select specific columns
- [ ] Services are not aware of HTTP — no `Request`, `Response`, or status code imports in `app/services/`
- [ ] Routers contain no business logic — they validate input, call a service, and return a response

## Celery Tasks

- [ ] New tasks are registered in `app/tasks/celery_app.py`
- [ ] Tasks are idempotent — safe to re-run if a worker crashes mid-execution
- [ ] Tasks use exponential backoff retry — no infinite retries
- [ ] Tasks accept IDs (not full objects) and load data themselves
- [ ] Task failures write a visible error state to the affected entity — never silently drop

## Pre-Push Local CI Checklist

Run these from `backend/` before every `git push`:

```bash
# Fix import order and unused imports
ruff check --fix .

# Format all files
ruff format .

# Confirm zero lint errors
ruff check .

# Type check
mypy

# Run unit tests with coverage (must stay ≥ 80%)
pytest -m "not integration" --cov=app --cov-report=term-missing
```

**Common CI failures:**

| Failure | Fix |
|---|---|
| `I001 Import block is un-sorted` | `ruff check --fix .` |
| `F401 imported but unused` | `ruff check --fix .` |
| `Would reformat: ...` | `ruff format .` |
| Coverage < 80% | Add unit tests for new code paths |
| `mypy` errors | Add return type annotations; resolve `Any` types |
