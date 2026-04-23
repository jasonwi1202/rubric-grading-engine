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
- [ ] **Prompt constraints must be consistent across the system prompt, the JSON schema description, and the parser** \u2014 e.g., if the system prompt says "minimum 20 words" for justification, the JSON schema description and the parser must also enforce 20 words (not 20 characters). Mismatched constraints produce conflicting model guidance and confusing parser behavior.

Reference: `docs/architecture/security.md#1-prompt-injection-defense`

## FERPA / Student Data

- [ ] No student PII (name, essay content, grades) in any log statement — use entity IDs only
- [ ] Essay content is never logged at any level in production code paths
- [ ] No student data is sent to third-party services not covered by a DPA
- [ ] Student data is never used for LLM fine-tuning or model training
- [ ] **Free-form text fields are not assumed to be PII-free** — fields like `CommentBankEntry.text`, `feedback`, or any teacher-entered freeform field can contain student names or identifiers. Do not document them as "no student PII" and never log their content.
- [ ] **S3 object keys are never logged or included in exception messages** — keys are often derived from user-supplied filenames which can contain student PII. Log only the operation type and entity ID. Raise `StorageError` with a generic message, chaining the original exception for debugging only.

Reference: `docs/architecture/security.md#5-ferpa-compliance`

## Audit Log

Every endpoint that changes grade state or performs a consequential access/admin action must write an audit log entry. See the full action catalog in `docs/architecture/data-model.md#auditlog`.

- [ ] **Any new `action` value used in an audit log entry must be added to the action catalog** in `docs/architecture/data-model.md#auditlog`. Using an undocumented action code creates unhandled cases when the frontend or reports branch on `action`.
- [ ] **`score_clamped` entries must use the `CriterionScore.id` as `entity_id`** (not the rubric criterion UUID), so audit queries can join back to the exact score row. `before_value` must be `{"raw_score": N}` and `after_value` must be `{"clamped_score": N}`.
- [ ] **State transitions that produce audit entries must be atomic** — e.g., `lock_grade()` can race under concurrent requests (two transactions both see `is_locked=False`). Use a conditional `UPDATE ... WHERE is_locked = false` and check `rowcount` to ensure only one caller writes the audit entry.

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

## Structured Logging

- [ ] **All error log calls include `error_type=type(exc).__name__`** — do NOT log `str(exc)` or pass `exc_info=exc` directly. Exception messages can contain user-controlled strings that may include student PII. Bind `error_type` only.
- [ ] **Error responses never contain `str(exc)` verbatim** — exception messages from framework internals or upstream services can expose implementation details. Return a static, stable message string; do not pass the exception string to `_error_response()` or the `message` field.
- [ ] **Unused injected dependencies are removed** — if a router injects `db: AsyncSession = Depends(get_db)` but never uses it, remove the parameter. An open DB connection is allocated per request regardless of usage.

## Authentication Error Codes

- [ ] **Missing or invalid credentials return HTTP 401, not 403 or 422** — the frontend silent-refresh cycle is triggered specifically on 401. Returning 403 (missing credentials) or 422 (expired token validation error) prevents the refresh-cookie reauth path from firing and strands the session.
- [ ] `get_current_teacher` raises `UnauthorizedError` (mapped to 401) for missing, expired, or malformed tokens — not `ForbiddenError` (403) or `ValidationError` (422).

## Code Quality

- [ ] All public functions have type annotations (`mypy` strict)
- [ ] `ruff check .` passes with zero errors from `backend/`
- [ ] `ruff format --check .` passes with zero "would reformat" files from `backend/`
- [ ] **No `# type: ignore` without a specific error code AND an inline explanation** — use `# type: ignore[call-overload]  # reason`, not a bare `# type: ignore`. Always try to remove the ignore first by narrowing types or adding an explicit `cast()`; the ignore is the last resort.
- [ ] SQLAlchemy queries use `AsyncSession` — no synchronous DB calls in async endpoints
- [ ] **`db.add()` and `db.delete()` are synchronous** — do NOT `await` them. Only `db.flush()`, `db.commit()`, `db.refresh()`, and `db.execute()` are awaitable. Awaiting a synchronous method silently awaits `None` in production and causes `AsyncMock` mismatches in tests.
- [ ] **No blocking CPU or sync I/O inside `async def` functions** — `bcrypt.hashpw()` is CPU-bound and will stall the event loop. Use `anyio.to_thread.run_sync()` / `starlette.concurrency.run_in_threadpool()`. Redis calls must use `redis.asyncio.Redis`, not the synchronous `redis.Redis` client.
- [ ] **`asyncio.get_event_loop()` is deprecated on Python 3.12+** — use `asyncio.get_running_loop()` in code that already runs inside an async context, or `asyncio.run()` to start a new event loop.
- [ ] No `SELECT *` — always select specific columns
- [ ] Services are not aware of HTTP — no `Request`, `Response`, or status code imports in `app/services/`
- [ ] Routers contain no business logic — they validate input, call a service, and return a response
- [ ] **`StrEnum` values must be accessed via `.value` or passed directly, not via `str()`** — `str(FeedbackTone.direct)` produces `"FeedbackTone.direct"` (the repr), not `"direct"`. Use `tone.value` or rely on `StrEnum` auto-coercion when passing to string contexts.
- [ ] **`None` and empty list `[]` are distinct — treat them separately in service functions** — `if essay_ids:` is falsy for both `None` and `[]`, causing an empty list to be silently ignored and the full dataset to be processed. Use `if essay_ids is not None:` to distinguish "not provided" from "provided but empty".
- [ ] **Status transitions that gate subsequent I/O must be committed last or rolled back on failure** — committing an assignment/essay status change before Redis initialization or Celery enqueue leaves the status stuck if the subsequent step fails. Either defer the commit until all side effects succeed, or roll back the status on exception.
- [ ] **Non-fatal side effects (Redis progress updates, notifications) must be caught and logged, not allowed to propagate** — a transient Redis outage should not fail an otherwise-successful grading write. Wrap best-effort operations in `try/except` with structured error logging.
- [ ] **Score overrides must be validated against `rubric_snapshot` min/max, not the live rubric** — the rubric may have changed since assignment creation. Read `assignment.rubric_snapshot` to find the criterion bounds and raise a domain `ValidationError` when `teacher_score` is out of range.
- [ ] **`total_score` must be recomputed after any criterion override** — `CriterionScore.final_score` changes but `Grade.total_score` is a stored aggregate. Recalculate from all criterion scores before committing the override.
- [ ] **Hard deletes require explicit justification** — the API conventions define DELETE as soft delete (`deleted_at`). If a resource genuinely warrants hard delete, document why in a comment and ensure list/suggest queries filter out deleted entries.
- [ ] **Docstrings and inline comments must accurately describe the actual implementation** — a docstring that describes aspirational or draft behavior, references a function that doesn't exist, or documents a pipeline that has since changed is worse than no docstring. Before committing, read each docstring in modified files and verify it matches what the code actually does. Pay special attention to: step-by-step pipeline descriptions, "this function is idempotent" claims, and cross-references to other functions.

## Celery Tasks

- [ ] New tasks are registered in `app/tasks/celery_app.py`
- [ ] **Tasks accept only IDs, never full entity objects** — passing full data into a task payload means retries use stale data from the original enqueue, not the current state. Tasks must load their own data from the DB using the ID.
- [ ] **Tasks use exponential backoff** — do not set a fixed `default_retry_delay`. Use `countdown=2 ** self.request.retries` or equivalent. A fixed delay defeats the retry strategy during outages.
- [ ] Tasks are idempotent — safe to re-run if a worker crashes mid-execution
- [ ] **Celery task error handlers must not unconditionally revert state** — a `_revert_to_queued` helper called from a broad `except Exception` block will downgrade a legitimately `graded` essay if the failure is a `ConflictError` (e.g., duplicate grade). Handle `ConflictError` and other non-"stuck" failures explicitly without reverting, and only revert when the current status is actually the in-progress state (e.g., `grading`).
- [ ] **Scan/batch tasks must be truly idempotent** — if a scheduled task can be triggered twice in the same window (e.g., by a cron overlap), verify it does not produce duplicate side effects (e.g., duplicate emails). Document the invariant in a comment.
- [ ] **Task configuration values come from `settings.*`** — do not hardcode `result_expires`, `task_soft_time_limit`, or queue names inline. Hardcoded values cause staging/prod drift.
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
