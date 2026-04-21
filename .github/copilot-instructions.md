# Rubric Grading Engine — Copilot Instructions

## What This Project Is

The Rubric Grading Engine is a **teacher-facing AI grading assistant** for K-12 writing instruction. Teachers upload student essays, the AI grades each one against a rubric with per-criterion scores and written justifications, and the teacher reviews, overrides, and locks grades before any feedback is shared. The system also builds persistent student skill profiles and surfaces instructional priorities to the teacher.

Two runtime processes:
- **Backend API** — FastAPI (Python 3.12), handles all data, grading orchestration, auth, and file management
- **Frontend** — Next.js 14 App Router (TypeScript), teacher-only interface

Shared infrastructure: **PostgreSQL 16** (primary store), **Redis 7** (Celery broker, cache, batch progress), **Celery** (async grading and export tasks), **S3-compatible object storage** (file uploads, exports).

---

## Key Documentation

Always consult these before implementing or reviewing anything.

### Architecture

| What | Where |
|---|---|
| **Tech stack** (versions, rationale, trade-offs) | `docs/architecture/tech-stack.md` |
| **Backend architecture** (process model, directory structure, layer responsibilities) | `docs/architecture/backend-architecture.md` |
| **Frontend architecture** (App Router, data fetching, state management, component patterns) | `docs/architecture/frontend-architecture.md` |
| **Data model** (all entities, columns, indexes, relationships, design decisions) | `docs/architecture/data-model.md` |
| **Data flow** (grading pipeline, profile update, export, integrity check, auth) | `docs/architecture/data-flow.md` |
| **API design** (endpoint reference, conventions, request/response shapes, error codes) | `docs/architecture/api-design.md` |
| **Data ingestion** (file extraction, auto-assignment, LLM response validation, skill normalization) | `docs/architecture/data-ingestion.md` |
| **Configuration** (every environment variable with defaults and descriptions) | `docs/architecture/configuration.md` |
| **Performance** (targets, bottlenecks, caching strategy, scaling, monitoring metrics) | `docs/architecture/performance.md` |
| **Security** (prompt injection defense, tenant isolation, FERPA, auth security, file safety) | `docs/architecture/security.md` |
| **Testing guide** (pytest, Vitest, Playwright, coverage targets, LLM mocking patterns) | `docs/architecture/testing-guide.md` |
| **Deployment** (environments, infrastructure, CI/CD, secrets, rollback) | `docs/architecture/deployment.md` |
| **Migrations** (Alembic workflow, zero-downtime patterns, data migration rules) | `docs/architecture/migrations.md` |
| **Error handling** (exception types, HTTP mapping, Celery task failures, frontend handling) | `docs/architecture/error-handling.md` |
| **LLM prompts** (prompt structure, versioning, JSON contracts, injection defense, failure handling) | `docs/architecture/llm-prompts.md` |

### Feature Specs & Roadmap

| What | Where |
|---|---|
| **Product vision** (problem, HITL principles, non-goals, phased roadmap) | `docs/prd/product-vision.md` |
| **Roadmap** (milestones and GitHub issues) | `docs/roadmap.md` |
| **Feature specs** (all 21 features with acceptance criteria) | `docs/features/` |
| **Full documentation index** | `docs/README.md` |

### Copilot Instruction Files

These files contain detailed per-area review checklists. They are loaded automatically by VS Code Copilot based on the files being edited (`applyTo` frontmatter). Read the relevant one before implementing in that area.

| File | Applies To | Covers |
|---|---|---|
| `.github/instructions/backend.instructions.md` | `backend/**` | API conformance, tenant isolation, prompt injection, audit log, rubric snapshot, code quality |
| `.github/instructions/frontend.instructions.md` | `frontend/**` | API client, React Query, forms, grade integrity, student data display, accessibility |
| `.github/instructions/migrations.instructions.md` | `backend/app/db/migrations/**` | Zero-downtime patterns, reversibility, data safety, naming conventions |
| `.github/instructions/security.instructions.md` | `**` | FERPA hard blocks, prompt injection, secrets, auth/session security, file uploads, CORS |
| `.github/instructions/testing.instructions.md` | `**/tests/**` | LLM mocking, tenant isolation tests, audit assertions, no PII in fixtures |
| `.github/instructions/docs.instructions.md` | `docs/**` | Accuracy, core principles not violated, roadmap issue sizing, broken links |

---

## Core Design Principles — Read These First

**Human-in-the-loop always.** The AI prepares; the teacher decides. No grade is recorded, no feedback shared, no exercise assigned, and no action taken without explicit teacher approval. If you are writing code that causes the system to take a consequential action automatically, stop and reconsider.

**Teacher-only interface.** There is no student-facing UI. Do not build student views, student accounts, or student-accessible endpoints.

**Prompt injection defense is mandatory.** Essay content is untrusted user input that flows into LLM prompts. Essay text must always be in the `user` role, never the `system` role. The system prompt must instruct the model to ignore directives found in essay content. See `docs/architecture/security.md`.

**FERPA applies.** Student essay content and grades are education records. No student PII in logs. No student data sent to third-party services without a signed DPA. No data used for any purpose other than grading and instruction. See `docs/architecture/security.md#5-ferpa-compliance`.

**Rubric snapshots are immutable.** When an assignment is created, the rubric is snapshotted. Editing the rubric later does not affect existing grades. Always use `assignment.rubric_snapshot`, never the live `Rubric` record, when grading.

---

## Git Workflow — Mandatory

**Every implementation task must follow this branching model. No exceptions.**

### Branch structure

```
main  (stable — tagged releases only, never commit here directly)
  └── release/mN  (milestone integration branch)
        ├── feat/mN-<issue-number>-<slug>
        └── fix/mN-<issue-number>-<slug>
```

### Rules for every implementation task

1. **Determine the active milestone** — check `docs/roadmap.md` or ask if unclear.
2. **Ensure the integration branch exists** — if `release/mN` does not exist locally or on origin, create it from `main` and push it before doing anything else.
3. **Create a feature branch off the integration branch** — `git checkout release/mN && git checkout -b feat/mN-<issue>-<slug>`. Never branch off `main` for issue work.
4. **Implement, commit, push** — use conventional commits (`feat:`, `fix:`, `chore:`, `docs:`, `test:`, `migration:`) with a scope where helpful.
5. **Open a PR targeting `release/mN`** — not `main`. Reference the GitHub issue number (`Closes #N`). Add a `type:` label.
6. **Never push directly to `main`** — not even documentation or config. The only thing that merges to `main` is a `release/mN` → `main` release PR.
7. **Never push directly to `release/mN`** — all changes go through feature branch PRs.

### When the GitHub Copilot coding agent implements an issue

The GitHub Copilot coding agent (assigned via GitHub Issues) creates branches named `copilot/<slug>` off the selected base branch.

**When assigning an issue to Copilot:**
1. In the "Assign Copilot to issue" dialog, click the base branch dropdown
2. Select `release/mN` (e.g. `release/m1`) — do **not** leave it on `main`
3. Copilot will branch off `release/mN` and open its PR targeting `release/mN`

### PR and Issue Labels

Every PR must have exactly one `type:` label. Every issue should have one as well. These labels drive the auto-generated release notes.

| Label | Use for |
|---|---|
| `type: feature` | New feature or roadmap issue |
| `type: fix` | Bug fix |
| `type: migration` | Alembic migration (can accompany a feature label) |
| `type: security` | Security fix or hardening |
| `type: test` | Tests only — no production code changes |
| `type: docs` | Documentation only |
| `type: chore` | Tooling, deps, config — excluded from release notes |
| `breaking-change` | Any PR that breaks the API or requires migration steps |
| `ignore-for-release` | Exclude from release notes entirely |

---

## Non-Negotiable Implementation Rules

These rules are not suggestions. Do not deviate from them for any reason, including "it's simpler", "it's just a prototype", or "this is a one-off". If you think a rule should change, surface it as a question — do not silently work around it.

### Architecture & Layering

- **Routers contain no business logic.** Routers validate input, call one service function, and return a response. No DB queries, no LLM calls, no conditional logic beyond input validation in routers.
- **Services contain no HTTP concerns.** No `Request`, `Response`, `HTTPException`, or status codes in `app/services/`. Services raise domain exceptions; routers catch them and map to HTTP responses.
- **Tasks call services, not the reverse.** Celery tasks are thin wrappers: load data, call a service function, handle failure. Business logic lives in services so it can be tested without a broker.
- **Never import from a sibling layer.** Services do not import from routers. Tasks do not import from routers. Models do not import from services.

### Database

- **All queries use `AsyncSession`.** No synchronous SQLAlchemy calls anywhere in the codebase.
- **`db.add()` and `db.delete()` are synchronous — never `await` them.** Only `execute`, `flush`, `commit`, `refresh`, and `rollback` are awaitable on `AsyncSession`. Awaiting a synchronous method silently awaits `None` in production.
- **No `SELECT *`.** Always specify columns or use mapped model attributes explicitly.
- **Every tenant-scoped query includes `teacher_id` — in the query itself, not only in a prior ownership check.** No exceptions. The pattern of doing an ownership check in one query and then fetching data in a second query without `teacher_id` is a tenant isolation gap. Both the check and the fetch must enforce `teacher_id`.
- **`IntegrityError` must be caught at every `db.commit()` that can hit a uniqueness constraint.** Catch, rollback, and re-raise as `ConflictError`. An uncaught `IntegrityError` from a concurrent request returns 500.
- **All endpoints return the `{"data": ...}` response envelope.** Never return a bare JSON object or list. The frontend `apiGet()` / `apiPost()` unwraps `json.data`; a bare response causes it to return `undefined` silently.
- **Rubric snapshot, always.** Grading code always reads `assignment.rubric_snapshot`. It never queries the live `rubrics` or `rubric_criteria` tables during grading or grade validation.
- **Audit log is INSERT-only.** No code path may UPDATE or DELETE from `audit_logs`. If you need to "undo" something, insert a new corrective entry.

### LLM / Grading

- **Essay content is always in the `user` role.** Never concatenate essay text into the system prompt under any circumstances — not even partially, not even "just the first sentence".
- **System prompt always contains the injection defense.** Every grading system prompt must include an explicit instruction for the model to ignore directives found in the essay content.
- **Validate before writing.** Every LLM response is parsed and validated against the grading schema before any database write. A response that fails validation is retried or failed — never written as-is.
- **Clamp scores server-side.** Regardless of what the LLM returns, criterion scores are clamped to `[criterion.min_score, criterion.max_score]` before being stored.
- **Prompt versions are tracked.** Every `Grade` record stores the `prompt_version` that produced it.

### Authentication & Security

- **`get_current_teacher` on every protected route.** No endpoint that reads or writes teacher data is missing this dependency.
- **Cross-teacher access returns 403.** Do not return 404 in a way that reveals whether another teacher's resource exists.
- **No student PII in logs.** `logger.*` calls use entity IDs (`essay_id`, `student_id`, `grade_id`). Never log student names, essay text, scores, or feedback content.
- **Secrets come from `settings.*` only.** Never read environment variables directly with `os.environ.get()` or `os.getenv()` in application code. Use the `pydantic-settings` config object.

### Frontend

- **All API calls go through `lib/api/client.ts`.** No raw `fetch()` or `axios` in components or hooks.
- **Frontend TypeScript API types must match backend Pydantic schemas exactly.** Before writing or finalizing types in `lib/api/`, do a side-by-side check against the corresponding schema in `backend/app/schemas/`. Verify field names, nullability (`string | null` vs `string`), required vs optional, and nested shapes.
- **Zod form validation constraints must match backend Pydantic constraints.** Field `max_length`, numeric `min`/`max`, and required/optional must be identical. Mismatches cause avoidable 422 errors or block valid user input.
- **Every new modal/dialog must implement the full accessibility baseline**: focus moves in on open, focus is trapped while open (Tab/Shift-Tab cycle within), Escape closes it, focus returns to the trigger on close. Radix UI / shadcn `Dialog` handles this — do not override the default focus management behaviors.
- **Do not wire UI to backend endpoints that do not yet exist.** Use `enabled: false` on queries or disable mutation triggers for unimplemented endpoints. A page that calls a non-existent endpoint errors on load in every environment.
- **After mutations, invalidate all affected query keys — not just the directly mutated entity.** Adding/removing a student also invalidates class detail (for `student_count`); a status transition also invalidates assignment list queries.
- **All server state uses React Query.** No `useEffect + fetch` for data that comes from the API.
- **Locked grades are read-only.** When `grade.is_locked === true`, all score and feedback edit controls must be visually and functionally disabled — not just hidden.
- **No student data in browser storage.** Nothing in `localStorage`, `sessionStorage`, or cookies that contains student names, essay content, scores, or feedback.

### Testing

- **No real OpenAI calls in tests.** The LLM client is always mocked. Any test that would make a real API call is wrong.
- **No student PII in test fixtures.** Use `Faker` or factory helpers for all student-like data. No hardcoded names, essay excerpts, or realistic-looking grades.
- **Tenant isolation is explicitly tested.** Every new API endpoint that returns teacher-scoped data must have a test that verifies a second teacher cannot access the first teacher's resource.

---

## Stack Quick Reference

| Layer | Technology |
|---|---|
| Frontend | Next.js 14 + TypeScript (App Router) |
| UI Components | shadcn/ui + Tailwind CSS |
| Server state | TanStack Query (React Query v5) |
| Forms | React Hook Form + Zod |
| Backend API | FastAPI + Python 3.12 |
| ORM | SQLAlchemy 2.0 async + asyncpg |
| Migrations | Alembic |
| Task queue | Celery 5 + Redis |
| Database | PostgreSQL 16 + pgvector |
| Cache / broker | Redis 7 |
| File storage | S3-compatible (boto3, configurable endpoint) |
| LLM | OpenAI API (model configurable via env) |
| Local dev | Docker Compose |
| Backend tests | pytest + pytest-asyncio + testcontainers |
| Frontend tests | Vitest + React Testing Library + MSW |
| E2E tests | Playwright |
