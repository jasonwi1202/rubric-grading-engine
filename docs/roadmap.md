# Roadmap

This roadmap is organized into GitHub Milestones. Each milestone maps to a product phase. Issues within each milestone are sized to be completable by an AI coding agent (Claude) in a focused session — roughly one feature area, one layer, or one well-defined integration per issue.

Issues are ordered within each milestone by dependency: earlier issues should be completed before later ones.

---

## How to Use This

1. Create each milestone in GitHub with the name and description below
2. Create each issue under the appropriate milestone
3. Assign issues to yourself or leave unassigned for AI agent pickup
4. Issues marked **[BLOCKER]** must be completed before dependent issues can start

---

## Milestone 0 — Project Scaffold

> Set up the monorepo, tooling, CI, and local dev environment. No product features yet. Everything in Milestone 1 depends on this being done first.

| # | Issue Title | Description |
|---|---|---|
| ~~0.1~~ | ~~Initialize monorepo structure~~ | ✅ Done — `backend/`, `docs/`, root `README.md`, `.gitignore`, `.env.example` all exist. |
| 0.2 | Bootstrap FastAPI backend | `backend/pyproject.toml` and `backend/Dockerfile` exist. Create `backend/app/main.py` with app factory, health check endpoint `GET /api/v1/health`, and global exception handlers per `docs/architecture/error-handling.md`. |
| 0.3 | Bootstrap Next.js frontend | `create-next-app` with TypeScript, App Router, Tailwind CSS. Install shadcn/ui, React Query, React Hook Form, Zod. Create base layout, `middleware.ts` stub, and `lib/api/client.ts` base fetch wrapper. Create `frontend/Dockerfile`. |
| ~~0.4~~ | ~~Set up Docker Compose for local dev~~ | ✅ Done — `docker-compose.yml` defines all 7 services with health checks and volume mounts. |
| 0.5 | Configure Alembic and initial database connection | Set up `alembic.ini`, `env.py`, and `db/session.py` async session factory. Verify migrations run cleanly against the Compose Postgres instance. |
| ~~0.6~~ | ~~Set up CI pipeline~~ | ✅ Done — `.github/workflows/ci.yml` covers ruff, mypy, pytest, vitest, eslint, tsc, pip-audit, npm audit. |
| 0.7 | Set up Celery worker and Redis connection | Wire Celery app in `tasks/celery_app.py`. Write a smoke-test task. Verify task enqueues and executes via Compose. |
| 0.8 | Configure S3/MinIO client and bucket | Set up `storage/s3.py` boto3 wrapper with configurable endpoint URL. MinIO bucket is created by the `minio-init` service in Compose. Verify upload and pre-signed URL generation. |
| 0.9 | Implement JWT authentication (backend) | `POST /auth/login`, `POST /auth/refresh`, `POST /auth/logout`. JWT access token + httpOnly refresh cookie. FastAPI dependency `get_current_teacher` for route protection. Rate limiting on auth endpoints. |
| 0.10 | Implement authentication (frontend) | Login page, `middleware.ts` route protection for `(dashboard)` routes. API client attaches Bearer token. Silent refresh on 401. Redirect to login on auth failure. |

---

## Milestone 1 — Foundation (Phase 1)

> Best-in-class rubric-based grading with transparent, editable AI feedback. This milestone produces the core product.

### Database & Models

| # | Issue Title | Description |
|---|---|---|
| 1.1 | **[BLOCKER]** Write initial Alembic migration: core schema | Create tables: `users`, `classes`, `class_enrollments`, `students`, `rubrics`, `rubric_criteria`, `assignments`, `essays`, `essay_versions`, `grades`, `criterion_scores`, `audit_logs`. All relationships, indexes, and constraints per the data model doc. |

### Rubric Builder

| # | Issue Title | Description |
|---|---|---|
| 1.2 | Rubric CRUD API | `GET/POST /rubrics`, `GET/PATCH/DELETE /rubrics/{id}`, `POST /rubrics/{id}/duplicate`. Rubric service with weight-sum validation (must equal 100%). Rubric snapshot logic. |
| 1.3 | Rubric Builder UI | Criterion list with add/edit/delete/reorder (drag-and-drop). Per-criterion name, description, weight, min/max score, anchor descriptions. Weight sum indicator. Save/cancel flow. |
| 1.4 | Rubric templates | 3 system-provided starter templates (5-paragraph essay, argumentative, research paper). Teacher can save any rubric as a personal template. Template picker in rubric builder and assignment creation. |

### Class & Student Management

| # | Issue Title | Description |
|---|---|---|
| 1.5 | Class CRUD API | `GET/POST /classes`, `GET/PATCH /classes/{id}`, `POST /classes/{id}/archive`. Scoped to authenticated teacher. Academic year field. |
| 1.6 | Student & enrollment API | `GET/POST /classes/{id}/students`, `DELETE /classes/{id}/students/{studentId}`, `GET/PATCH /students/{id}`. Student persistence model (students independent of classes). ClassEnrollment join table with soft removal. |
| 1.7 | CSV roster import | `POST /classes/{id}/students/import` with CSV upload. Parse `full_name`, `external_id` columns. Duplicate detection. Return diff (new / updated / skipped) for teacher confirmation before committing. |
| 1.8 | Class and roster management UI | Class creation form. Roster list view. Add student manually. CSV import flow with diff confirmation screen. Remove student (soft). |

### Essay Input & Ingestion

| # | Issue Title | Description |
|---|---|---|
| 1.9 | Essay upload API and file extraction | `POST /assignments/{id}/essays` multipart upload. MIME validation, size limit. Store raw file to S3. Extract text from PDF (`pdfplumber`), DOCX (`python-docx`), TXT. Normalize extracted text. Compute word count. Create `Essay` + `EssayVersion` records. |
| 1.10 | Student auto-assignment on upload | Fuzzy match essay filename, DOCX author metadata, and header text against class roster. Auto-assign when confidence ≥ 0.85 and only one student matches. All others go to unassigned queue. Flag name collisions. |
| 1.11 | Essay input UI | Single and multi-file upload with drag-and-drop. Text paste input. Upload progress. Auto-assignment results review screen (show matches, flag uncertain, allow manual correction before proceeding). |

### Assignment Management

| # | Issue Title | Description |
|---|---|---|
| 1.12 | Assignment CRUD API | `GET/POST /classes/{id}/assignments`, `GET/PATCH /assignments/{id}`. Status state machine (`draft → open → grading → review → complete → returned`). Rubric snapshot written at creation time. |
| 1.13 | Assignment UI | Assignment creation form (title, prompt, rubric picker, due date). Assignment overview page showing submission status per student (submitted / pending / graded / returned). Status transition controls. |

### AI Grading Engine

| # | Issue Title | Description |
|---|---|---|
| 1.14 | **[BLOCKER]** LLM client and prompt infrastructure | `llm/client.py` OpenAI wrapper with retry, timeout, error normalization. Versioned prompt templates in `llm/prompts/`. Prompt injection defenses: essay content in user role, system prompt instructs model to ignore directives in essay. |
| 1.15 | Grading Celery task | `grade_essay` task: load essay + rubric snapshot + strictness config, construct grading prompt, call LLM, parse and validate structured response, write `Grade` + `CriterionScore` records. Handle all LLM failure modes (parse error, missing criterion, out-of-range score, timeout). |
| 1.16 | Batch grading API and progress tracking | `POST /assignments/{id}/grade` enqueues one task per essay. Returns 202. Redis progress counter per assignment. `GET /assignments/{id}/grading-status` reads from Redis. Assignment status transitions. Per-essay retry endpoint. |
| 1.17 | Batch grading UI | "Grade now" trigger button. Real-time progress bar (polls every 3 seconds, stops on completion). Per-essay status list. Failed essay display with retry action. In-app notification on completion. |

### Feedback Generator

| # | Issue Title | Description |
|---|---|---|
| 1.18 | Feedback generation in grading task | Extend grading prompt/response to include: per-criterion feedback note, overall summary feedback paragraph. Tone parameter (encouraging / direct / academic) injected from assignment config. Both AI score and feedback stored on `CriterionScore` and `Grade`. |
| 1.19 | Comment bank API | `GET/POST /comment-bank`, `DELETE /comment-bank/{id}`. Save any feedback snippet. Suggest saved comments when grading similar issues (fuzzy match). Scoped to teacher. |

### Teacher Review & Control

| # | Issue Title | Description |
|---|---|---|
| 1.20 | Grade read and edit API | `GET /essays/{id}/grade`, `PATCH /grades/{id}/feedback`, `PATCH /grades/{id}/criteria/{criterionId}`, `POST /grades/{id}/lock`. All edits write to audit log (before/after values). Locked grades reject further edits. |
| 1.21 | Essay review interface (core) | Two-panel layout: essay text left, rubric scores + feedback right. Display per-criterion score, AI justification, feedback. Inline score override control. Inline feedback text editor. Weighted total recalculates on override. Lock grade button. |
| 1.22 | Review queue UI | List view of all essays in an assignment. Status badges (unreviewed / in-review / locked). Sort/filter by status, score range, student name. Keyboard navigation. Link through to individual essay review. |
| 1.23 | Audit log API | `GET /grades/{id}/audit`. Returns full change history for a grade with timestamps, actor, before/after values. |

### Export

| # | Issue Title | Description |
|---|---|---|
| 1.24 | Export API and Celery task | `POST /assignments/{id}/export` enqueues export task. Task generates per-student feedback PDFs using a template, packages as ZIP, uploads to S3. `GET /exports/{taskId}/status` polls progress. `GET /exports/{taskId}/download` returns pre-signed S3 URL. |
| 1.25 | CSV grade export | `GET /assignments/{id}/grades.csv` — synchronous export of all locked grades: student name, per-criterion scores, total. Compatible with LMS gradebook import formats. |
| 1.26 | Export UI | "Export" button on assignment view. Options: PDF batch ZIP, CSV grades, copy individual student feedback to clipboard. Download flow for async ZIP export. |

---

## Milestone 2 — Workflow (Phase 2)

> Confidence scoring, academic integrity, assignment workflow polish, regrade requests, and media feedback.

### Confidence Scoring

| # | Issue Title | Description |
|---|---|---|
| 2.1 | Confidence scoring in grading | Extend grading prompt/response to include `confidence` field per criterion (`high` / `medium` / `low`). Store on `CriterionScore`. Compute overall essay confidence from criteria. |
| 2.2 | Confidence-based review queue | Surface confidence indicator on each essay in review queue. Sort low-confidence first by default. Fast-review mode: filter to low-confidence only. Bulk-approve high-confidence essays (teacher-explicit action — never automatic). Show plain-language explanation of why a criterion is low-confidence. |

### Academic Integrity

| # | Issue Title | Description |
|---|---|---|
| 2.3 | Add `IntegrityReport` migration and model | Alembic migration for `integrity_reports` table. SQLAlchemy model. Relationship to `EssayVersion`. |
| 2.4 | Internal cross-submission similarity | Add `embedding` (pgvector) column to `essay_versions`. Compute embedding via OpenAI embeddings API in a Celery task on essay upload. Query for cosine similarity against same-assignment essays. Flag pairs above threshold. |
| 2.5 | Third-party integrity API integration | Abstract `IntegrityProvider` interface. Implement provider for Originality.ai or Winston AI (configurable via `INTEGRITY_PROVIDER` env var). Fallback to internal-only if provider unavailable. Write `IntegrityReport` record. |
| 2.6 | Integrity report API and UI | `GET /essays/{id}/integrity`. Per-essay integrity report panel in review interface (AI likelihood indicator, similarity score, flagged passages highlighted in essay text). Class-level integrity overview on assignment page. Teacher review status actions (`reviewed_clear`, `flagged`). All language framed as signals, not findings. |

### Regrade Requests

| # | Issue Title | Description |
|---|---|---|
| 2.7 | Regrade request data model and migration | Alembic migration for `regrade_requests` table (linked to grade, criterion, teacher_id, dispute text, status, resolution). |
| 2.8 | Regrade request API | `POST /grades/{id}/regrade-requests` (teacher logs on behalf of student or via form link). `GET /assignments/{id}/regrade-requests` (queue). `POST /regrade-requests/{id}/resolve` (approve with new score / deny with note). Configurable submission window. Request limit enforcement. Audit log entries on resolution. |
| 2.9 | Regrade request UI | Regrade queue view on assignment page. Log request form. Side-by-side review panel (essay, original score, justification). Approve/deny controls with required note on deny. Close regrade window action. Outcome tracking display. |

### Media Feedback

| # | Issue Title | Description |
|---|---|---|
| 2.10 | Media comment recording and storage | In-browser audio recording via MediaRecorder API. Max 3-minute limit. Upload to S3 on save. Associate with `Grade` or `CriterionScore`. API: `POST /grades/{id}/media-comments`, `DELETE /media-comments/{id}`. |
| 2.11 | Video comment recording | Extend media comment to support webcam + optional screen share. Same storage and association model. |
| 2.12 | Media comment bank and export | Save media comment to reusable bank. Apply saved comment to new essay in one action. Include media link/QR code in PDF export. Access-controlled pre-signed URLs for playback. |

---

## Milestone 3 — Student Intelligence (Phase 3)

> Persistent skill profiles, longitudinal tracking, class insights, and writing process visibility.

### Student Skill Profiles

| # | Issue Title | Description |
|---|---|---|
| 3.1 | **[BLOCKER]** Skill normalization layer | Configurable mapping from rubric criterion names to canonical skill dimensions (`thesis`, `evidence`, `organization`, `analysis`, `mechanics`, `voice`). Fuzzy match at grade-write time. Unmapped criteria stored under `other`. Mapping stored as config, not hardcoded. |
| 3.2 | `StudentSkillProfile` migration and model | Alembic migration. JSONB `skill_scores` column. Upsert logic. |
| 3.3 | Skill profile update Celery task | Triggered on grade lock. Load all locked criterion scores for student. Normalize to skill dimensions. Compute weighted average, trend direction, and data point count per skill. Upsert `StudentSkillProfile`. |
| 3.4 | Student profile API | `GET /students/{id}` with skill profile embedded. `GET /students/{id}/history` — all graded assignments chronologically. |
| 3.5 | Student profile UI | Skill radar or bar chart per dimension. Historical timeline of assignments with scores. Strengths and gaps callouts. Growth indicators (improved / regressed). Private teacher notes field. |

### Class Insights

| # | Issue Title | Description |
|---|---|---|
| 3.6 | Class insights API | `GET /classes/{id}/insights` — class average per skill dimension, score distributions, common issues aggregated from feedback. `GET /assignments/{id}/analytics` — per-assignment breakdown. |
| 3.7 | Skill heatmap UI | Grid: students as rows, skills as columns. Color-coded by score. Sortable by skill. Links to individual student profile. |
| 3.8 | Common issues and distribution UI | Ranked list of most-flagged issues across class with student counts. Histogram of score distribution per criterion. Outlier highlighting. Cross-assignment trend chart. |

### Writing Process Visibility

| # | Issue Title | Description |
|---|---|---|
| 3.9 | In-browser essay writing interface | Basic rich-text writing area within the assignment submission flow. Captures incremental changes (debounced saves every 10–15 seconds). Stores snapshots as JSONB in `essay_versions`. |
| 3.10 | Composition timeline and process signals | Parse snapshot history into session timeline. Detect: large paste events, rapid-completion events. Compute: session count, duration, inter-session gaps, active writing time. |
| 3.11 | Writing process visibility UI | Visual timeline in essay review interface. Session markers, paste event flags. Version snapshot viewer (view essay at any point in history). Process insight callout (e.g., "Written in a single 20-minute session"). |

---

## Milestone 4 — Prioritization & Instruction (Phase 4)

> Teacher worklist, auto-grouping, instruction recommendations, and resubmission loop.

### Auto-Grouping

| # | Issue Title | Description |
|---|---|---|
| 4.1 | Auto-grouping Celery task | After each batch of grades is locked, compute skill groups from updated `StudentSkillProfile` records. Cluster students by shared underperforming skill dimensions. Apply minimum group size threshold. Store groups as JSONB on class or as a separate `student_groups` table. |
| 4.2 | Auto-grouping API | `GET /classes/{id}/groups` — current groups with student lists, shared skill gap labels, and group stability data (persistent / new / exited). |
| 4.3 | Auto-grouping UI | Group list view (name, skill gap, student count). Expand to see individual students. Manual adjust (add/remove student from group). Cross-reference link to class heatmap. |

### Teacher Worklist

| # | Issue Title | Description |
|---|---|---|
| 4.4 | Worklist generation logic | Compute worklist from student profiles: persistent gap (same group 2+ assignments), regression (score drop), high inconsistency, non-responder (no improvement after resubmission). Rank by urgency. Link each item to a suggested action from the instruction engine. |
| 4.5 | Worklist API | `GET /worklist`, `POST /worklist/{id}/complete`, `POST /worklist/{id}/snooze`, `DELETE /worklist/{id}`. |
| 4.6 | Worklist UI | Ranked list with urgency indicators. Reason and suggested action per student. Mark done / snooze / dismiss controls. Filter by action type, skill gap, urgency. Default to top 10, expand to full class. |

### Instruction Engine

| # | Issue Title | Description |
|---|---|---|
| 4.7 | Instruction recommendation generation | LLM-powered recommendation generation for: mini-lessons (objective, structure, example), targeted exercises (single-skill prompts), intervention suggestions (1:1, reading scaffolds, peer review). Triggered from worklist items or student profile gaps. Evidence summary included with each recommendation. |
| 4.8 | Instruction API | `POST /students/{id}/recommendations` — generate recommendation for a student gap. `POST /classes/{id}/groups/{groupId}/recommendations` — for a group. `POST /recommendations/{id}/assign` — teacher assigns exercise to student/group (explicit teacher action). |
| 4.9 | Instruction recommendations UI | Recommendation card: objective, structure, evidence summary. Accept / modify / dismiss controls. Assign exercise flow (teacher confirms before any action is applied to student record). |

### Resubmission Loop

| # | Issue Title | Description |
|---|---|---|
| 4.10 | Resubmission intake and versioning | `POST /essays/{id}/resubmit` — submit new version. Store as new `EssayVersion` linked to same `Essay`. Configurable per-assignment limit. |
| 4.11 | Resubmission grading and comparison | Re-run grading task on resubmission. Score delta per criterion vs. original. Detect whether specific feedback points were addressed in revision. Flag low-effort revisions (surface-level changes). |
| 4.12 | Resubmission UI | Side-by-side diff view (original vs. revised). Score delta display per criterion. Feedback-addressed indicators. Version history list. Improvement signal in student profile. |

---

## Milestone 5 — Closed Loop (Phase 5)

> Automation agents and teacher copilot. Every prior milestone must be complete before starting this one.

### Automation Agents

| # | Issue Title | Description |
|---|---|---|
| 5.1 | Intervention agent | Background Celery task that scans student profiles on a schedule. Detects trigger conditions (persistent gap, regression, non-response). Prepares recommended action and adds to teacher worklist. Teacher approves or dismisses — nothing acts without confirmation. |
| 5.2 | Predictive insights | Detect early trajectory risk signals from skill profile trends (declining across 3+ assignments, persistent low score with no improvement). Surface as worklist item labeled as prediction. Include confidence indicator and supporting data points. |
| 5.3 | Teacher copilot — data query layer | LLM-backed query interface backed by real class data. Supports: "Who is falling behind on thesis?", "What should I teach tomorrow?", "Which students haven't improved since my last feedback?". Queries against live Postgres data. Returns ranked lists and summaries. Never fabricates — expresses uncertainty if data is insufficient. Security: strictly scoped to authenticated teacher's classes only. |
| 5.4 | Teacher copilot UI | Conversational input in sidebar or dedicated panel. Display structured response (ranked list, summary, or recommendation). Link-through to relevant students, assignments, or worklist items. No action taken from copilot — surfacing only. |

---

## Cross-Cutting Issues (Any Milestone)

These issues can be worked in parallel with any milestone they support.

| # | Issue Title | Description |
|---|---|---|
| X.1 | Security hardening | Implement all items in `security.md`: security response headers middleware, CORS allowlist, rate limiting middleware (Redis counters), RLS policies on all tenant-scoped tables, `pip-audit` in CI, `npm audit` in CI. |
| X.2 | Error handling and observability | Global FastAPI exception handler. Structured JSON logging throughout backend and Celery workers. No PII in any log line. Health check endpoints on all services. Correlation IDs on all requests. |
| X.3 | End-to-end tests (Playwright) | 5 critical E2E journeys: (1) login → class → students → rubric → assignment, (2) upload → auto-assign → grade batch → progress, (3) review → override score → edit feedback → lock, (4) export PDF ZIP → download, (5) view student profile across two assignments. |
| X.4 | Accessibility audit | Keyboard navigation throughout. ARIA labels on interactive elements. Focus management in modals and panels. Color contrast compliance. Screen reader testing on grading interface. |
| X.5 | `prompt_version` field on Grade | Add `prompt_version VARCHAR(20)` column to `grades` table via Alembic migration. Populate from `GRADING_PROMPT_VERSION` env var at grade-write time. |
