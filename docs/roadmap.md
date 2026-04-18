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

## Milestone Summary

| Milestone | Name | Description | Issues | Status |
|---|---|---|---|---|
| **M1** | Project Scaffold | Monorepo, CI, Docker Compose, authentication, and local dev environment. No product features — everything else depends on this. | 10 | ✅ Complete |
| **M2** | Public Website & Onboarding | Marketing site, legal pages, pricing, AI transparency page, sign-up, and trial onboarding wizard. Can be built in parallel with M3 once M1.2 and M1.3 are done. | 10 | ✅ Complete |
| **M3** | Foundation | Core product: rubric builder, class/roster management, essay upload and ingestion, AI grading engine, human-in-the-loop review interface, and export. | 26 | 🔲 Planned |
| **M4** | Workflow | Confidence scoring, academic integrity detection, regrade requests, and media (audio/video) feedback. | 12 | 🔲 Planned |
| **M5** | Student Intelligence | Persistent student skill profiles, longitudinal tracking, class insights heatmap, and writing process visibility. | 11 | 🔲 Planned |
| **M6** | Prioritization & Instruction | Auto-grouping by skill gap, teacher worklist, instruction engine recommendations, and resubmission loop. | 12 | 🔲 Planned |
| **M7** | Closed Loop | Automation agents, predictive insights, and teacher copilot (conversational data interface). Requires all prior milestones. | 9 | 🔲 Planned |
| **MX** | Cross-Cutting | Security hardening, observability, E2E tests, accessibility, and prompt version tracking. Can be worked in parallel with any milestone. | 5 | 🔄 Ongoing |
| | **Total** | | **95** | |

---

## M1 — Project Scaffold ✅ Complete

> Set up the monorepo, tooling, CI, and local dev environment. No product features yet. Everything in M3 depends on this being done first.

| # | Issue Title | Description |
|---|---|---|
| ~~M1.1~~ | ~~Initialize monorepo structure~~ | ✅ Done — `backend/`, `docs/`, root `README.md`, `.gitignore`, `.env.example` all exist. |
| M1.2 | Bootstrap FastAPI backend | `backend/pyproject.toml` and `backend/Dockerfile` exist. Create `backend/app/main.py` with app factory, health check endpoint `GET /api/v1/health`, and global exception handlers per `docs/architecture/error-handling.md`. |
| M1.3 | Bootstrap Next.js frontend | `create-next-app` with TypeScript, App Router, Tailwind CSS. Install shadcn/ui, React Query, React Hook Form, Zod. Create base layout, `middleware.ts` stub, and `lib/api/client.ts` base fetch wrapper. Create `frontend/Dockerfile`. |
| ~~M1.4~~ | ~~Set up Docker Compose for local dev~~ | ✅ Done — `docker-compose.yml` defines all 7 services with health checks and volume mounts. |
| M1.5 | Configure Alembic and initial database connection | Set up `alembic.ini`, `env.py`, and `db/session.py` async session factory. Verify migrations run cleanly against the Compose Postgres instance. |
| ~~M1.6~~ | ~~Set up CI pipeline~~ | ✅ Done — `.github/workflows/ci.yml` covers ruff, mypy, pytest, vitest, eslint, tsc, pip-audit, npm audit. |
| M1.7 | Set up Celery worker and Redis connection | Wire Celery app in `tasks/celery_app.py`. Write a smoke-test task. Verify task enqueues and executes via Compose. |
| M1.8 | Configure S3/MinIO client and bucket | Set up `storage/s3.py` boto3 wrapper with configurable endpoint URL. MinIO bucket is created by the `minio-init` service in Compose. Verify upload and pre-signed URL generation. |
| M1.9 | Implement JWT authentication (backend) | `POST /auth/login`, `POST /auth/refresh`, `POST /auth/logout`. JWT access token + httpOnly refresh cookie. FastAPI dependency `get_current_teacher` for route protection. Rate limiting on auth endpoints. |
| M1.10 | Implement authentication (frontend) | Login page, `middleware.ts` route protection for `(dashboard)` routes. API client attaches Bearer token. Silent refresh on 401. Redirect to login on auth failure. |

---

## M2 — Public Website & Onboarding ✅ Complete

> Public marketing site, legal pages, pricing, AI transparency, and trial sign-up flow. Must be complete before any real teacher data is collected. Can be built in parallel with M3 once M1.2 and M1.3 are done.

| # | Issue Title | Description |
|---|---|---|
| M2.1 | Public site layout and route structure | Shared public layout: site header (nav: Product, How It Works, Pricing, AI, About, Sign In, Start Trial CTA), footer (nav links + legal links). Route group `/(public)/` in Next.js App Router. `/(dashboard)/` route group for the app. `middleware.ts` redirects authenticated users from `/login` and `/signup` to `/dashboard`. Spec: `docs/features/public-website.md`. |
| M2.2 | Landing page (`/`) | Hero section, problem/solution block, feature highlight cards (3–4), abbreviated how-it-works steps, CTA section. All copy uses `PRODUCT_NAME` constant. Static page — no API calls. Spec: `docs/features/public-website.md`. |
| M2.3 | Product page (`/product`) and How It Works (`/how-it-works`) | `/product`: feature deep-dive sections with screenshot placeholders, trust/compliance callout. `/how-it-works`: numbered step-by-step workflow with visual timeline. Both static. Spec: `docs/features/public-website.md`. |
| M2.4 | About page (`/about`) | Mission statement, team placeholder, principles, contact. Static. Spec: `docs/features/public-website.md`. |
| M2.5 | Pricing page (`/pricing`) | Tier cards (Trial/Teacher/School/District), annual/monthly toggle, feature comparison table, FAQ accordion, school inquiry form. Inquiry form POSTs to `POST /api/v1/contact/inquiry` and sends notification email — no third-party form service. Spec: `docs/features/pricing-page.md`. |
| M2.6 | AI transparency page (`/ai`) | How the AI grades (5 steps), what it can/can't do, HITL guarantee callout, data use disclosure, confidence score explainer. Static. Spec: `docs/features/ai-transparency-page.md`. |
| M2.7 | Legal pages (`/legal/*`) | Terms of Service, Privacy Policy, FERPA/COPPA Notice, DPA info page, AI Use Policy. All static-rendered. DPA request form POSTs to backend (stored + email notification). "Last updated" date and version on each. All `[ATTORNEY DRAFT REQUIRED]` placeholders marked — page cannot deploy to production with placeholder text present. Spec: `docs/features/legal-pages.md`. |
| M2.8 | Sign-up flow (`/signup`) | Sign-up form with email/password + school name. Server-side account creation. Verification email via Celery task. `/signup/verify` holding page. Verification link handler. Rate limiting on sign-up endpoint. Spec: `docs/features/account-onboarding.md`. |
| M2.9 | Onboarding wizard (`/onboarding`) | 2-step wizard: create first class, build/import/skip rubric. Progress indicator. Skip available at each step. `/onboarding/done` completion page. Trial status banner in dashboard header. Spec: `docs/features/account-onboarding.md`. |
| M2.10 | Trial lifecycle emails | Celery-scheduled email tasks: trial expiry at 7 days, 1 day, and 0 days. Welcome email on verification. All emails are plain HTML. No student PII. Unsubscribe link on non-transactional emails. Spec: `docs/features/account-onboarding.md`. |

---

## M3 — Foundation

> Best-in-class rubric-based grading with transparent, editable AI feedback. This milestone produces the core product.

### Database & Models

| # | Issue Title | Description |
|---|---|---|
| M3.1 | **[BLOCKER]** Write initial Alembic migration: core schema | Create tables: `users`, `classes`, `class_enrollments`, `students`, `rubrics`, `rubric_criteria`, `assignments`, `essays`, `essay_versions`, `grades`, `criterion_scores`, `audit_logs`. All relationships, indexes, and constraints per the data model doc. |

### Rubric Builder

| # | Issue Title | Description |
|---|---|---|
| M3.2 | Rubric CRUD API | `GET/POST /rubrics`, `GET/PATCH/DELETE /rubrics/{id}`, `POST /rubrics/{id}/duplicate`. Rubric service with weight-sum validation (must equal 100%). Rubric snapshot logic. |
| M3.3 | Rubric Builder UI | Criterion list with add/edit/delete/reorder (drag-and-drop). Per-criterion name, description, weight, min/max score, anchor descriptions. Weight sum indicator. Save/cancel flow. |
| M3.4 | Rubric templates | 3 system-provided starter templates (5-paragraph essay, argumentative, research paper). Teacher can save any rubric as a personal template. Template picker in rubric builder and assignment creation. |

### Class & Student Management

| # | Issue Title | Description |
|---|---|---|
| M3.5 | Class CRUD API | `GET/POST /classes`, `GET/PATCH /classes/{id}`, `POST /classes/{id}/archive`. Scoped to authenticated teacher. Academic year field. |
| M3.6 | Student & enrollment API | `GET/POST /classes/{id}/students`, `DELETE /classes/{id}/students/{studentId}`, `GET/PATCH /students/{id}`. Student persistence model (students independent of classes). ClassEnrollment join table with soft removal. |
| M3.7 | CSV roster import | `POST /classes/{id}/students/import` with CSV upload. Parse `full_name`, `external_id` columns. Duplicate detection. Return diff (new / updated / skipped) for teacher confirmation before committing. |
| M3.8 | Class and roster management UI | Class creation form. Roster list view. Add student manually. CSV import flow with diff confirmation screen. Remove student (soft). |

### Essay Input & Ingestion

| # | Issue Title | Description |
|---|---|---|
| M3.9 | Essay upload API and file extraction | `POST /assignments/{id}/essays` multipart upload. MIME validation, size limit. Store raw file to S3. Extract text from PDF (`pdfplumber`), DOCX (`python-docx`), TXT. Normalize extracted text. Compute word count. Create `Essay` + `EssayVersion` records. |
| M3.10 | Student auto-assignment on upload | Fuzzy match essay filename, DOCX author metadata, and header text against class roster. Auto-assign when confidence ≥ 0.85 and only one student matches. All others go to unassigned queue. Flag name collisions. |
| M3.11 | Essay input UI | Single and multi-file upload with drag-and-drop. Text paste input. Upload progress. Auto-assignment results review screen (show matches, flag uncertain, allow manual correction before proceeding). |

### Assignment Management

| # | Issue Title | Description |
|---|---|---|
| M3.12 | Assignment CRUD API | `GET/POST /classes/{id}/assignments`, `GET/PATCH /assignments/{id}`. Status state machine (`draft → open → grading → review → complete → returned`). Rubric snapshot written at creation time. |
| M3.13 | Assignment UI | Assignment creation form (title, prompt, rubric picker, due date). Assignment overview page showing submission status per student (submitted / pending / graded / returned). Status transition controls. |

### AI Grading Engine

| # | Issue Title | Description |
|---|---|---|
| M3.14 | **[BLOCKER]** LLM client and prompt infrastructure | `llm/client.py` OpenAI wrapper with retry, timeout, error normalization. Versioned prompt templates in `llm/prompts/`. Prompt injection defenses: essay content in user role, system prompt instructs model to ignore directives in essay. |
| M3.15 | Grading Celery task | `grade_essay` task: load essay + rubric snapshot + strictness config, construct grading prompt, call LLM, parse and validate structured response, write `Grade` + `CriterionScore` records. Handle all LLM failure modes (parse error, missing criterion, out-of-range score, timeout). |
| M3.16 | Batch grading API and progress tracking | `POST /assignments/{id}/grade` enqueues one task per essay. Returns 202. Redis progress counter per assignment. `GET /assignments/{id}/grading-status` reads from Redis. Assignment status transitions. Per-essay retry endpoint. |
| M3.17 | Batch grading UI | "Grade now" trigger button. Real-time progress bar (polls every 3 seconds, stops on completion). Per-essay status list. Failed essay display with retry action. In-app notification on completion. |

### Feedback Generator

| # | Issue Title | Description |
|---|---|---|
| M3.18 | Feedback generation in grading task | Extend grading prompt/response to include: per-criterion feedback note, overall summary feedback paragraph. Tone parameter (encouraging / direct / academic) injected from assignment config. Both AI score and feedback stored on `CriterionScore` and `Grade`. |
| M3.19 | Comment bank API | `GET/POST /comment-bank`, `DELETE /comment-bank/{id}`. Save any feedback snippet. Suggest saved comments when grading similar issues (fuzzy match). Scoped to teacher. |

### Teacher Review & Control

| # | Issue Title | Description |
|---|---|---|
| M3.20 | Grade read and edit API | `GET /essays/{id}/grade`, `PATCH /grades/{id}/feedback`, `PATCH /grades/{id}/criteria/{criterionId}`, `POST /grades/{id}/lock`. All edits write to audit log (before/after values). Locked grades reject further edits. |
| M3.21 | Essay review interface (core) | Two-panel layout: essay text left, rubric scores + feedback right. Display per-criterion score, AI justification, feedback. Inline score override control. Inline feedback text editor. Weighted total recalculates on override. Lock grade button. |
| M3.22 | Review queue UI | List view of all essays in an assignment. Status badges (unreviewed / in-review / locked). Sort/filter by status, score range, student name. Keyboard navigation. Link through to individual essay review. |
| M3.23 | Audit log API | `GET /grades/{id}/audit`. Returns full change history for a grade with timestamps, actor, before/after values. |

### Export

| # | Issue Title | Description |
|---|---|---|
| M3.24 | Export API and Celery task | `POST /assignments/{id}/export` enqueues export task. Task generates per-student feedback PDFs using a template, packages as ZIP, uploads to S3. `GET /exports/{taskId}/status` polls progress. `GET /exports/{taskId}/download` returns pre-signed S3 URL. |
| M3.25 | CSV grade export | `GET /assignments/{id}/grades.csv` — synchronous export of all locked grades: student name, per-criterion scores, total. Compatible with LMS gradebook import formats. |
| M3.26 | Export UI | "Export" button on assignment view. Options: PDF batch ZIP, CSV grades, copy individual student feedback to clipboard. Download flow for async ZIP export. |

---

## M4 — Workflow

> Confidence scoring, academic integrity, assignment workflow polish, regrade requests, and media feedback.

### Confidence Scoring

| # | Issue Title | Description |
|---|---|---|
| M4.1 | Confidence scoring in grading | Extend grading prompt/response to include `confidence` field per criterion (`high` / `medium` / `low`). Store on `CriterionScore`. Compute overall essay confidence from criteria. |
| M4.2 | Confidence-based review queue | Surface confidence indicator on each essay in review queue. Sort low-confidence first by default. Fast-review mode: filter to low-confidence only. Bulk-approve high-confidence essays (teacher-explicit action — never automatic). Show plain-language explanation of why a criterion is low-confidence. |

### Academic Integrity

| # | Issue Title | Description |
|---|---|---|
| M4.3 | Add `IntegrityReport` migration and model | Alembic migration for `integrity_reports` table. SQLAlchemy model. Relationship to `EssayVersion`. |
| M4.4 | Internal cross-submission similarity | Add `embedding` (pgvector) column to `essay_versions`. Compute embedding via OpenAI embeddings API in a Celery task on essay upload. Query for cosine similarity against same-assignment essays. Flag pairs above threshold. |
| M4.5 | Third-party integrity API integration | Abstract `IntegrityProvider` interface. Implement provider for Originality.ai or Winston AI (configurable via `INTEGRITY_PROVIDER` env var). Fallback to internal-only if provider unavailable. Write `IntegrityReport` record. |
| M4.6 | Integrity report API and UI | `GET /essays/{id}/integrity`. Per-essay integrity report panel in review interface (AI likelihood indicator, similarity score, flagged passages highlighted in essay text). Class-level integrity overview on assignment page. Teacher review status actions (`reviewed_clear`, `flagged`). All language framed as signals, not findings. |

### Regrade Requests

| # | Issue Title | Description |
|---|---|---|
| M4.7 | Regrade request data model and migration | Alembic migration for `regrade_requests` table (linked to grade, criterion, teacher_id, dispute text, status, resolution). |
| M4.8 | Regrade request API | `POST /grades/{id}/regrade-requests` (teacher logs on behalf of student or via form link). `GET /assignments/{id}/regrade-requests` (queue). `POST /regrade-requests/{id}/resolve` (approve with new score / deny with note). Configurable submission window. Request limit enforcement. Audit log entries on resolution. |
| M4.9 | Regrade request UI | Regrade queue view on assignment page. Log request form. Side-by-side review panel (essay, original score, justification). Approve/deny controls with required note on deny. Close regrade window action. Outcome tracking display. |

### Media Feedback

| # | Issue Title | Description |
|---|---|---|
| M4.10 | Media comment recording and storage | In-browser audio recording via MediaRecorder API. Max 3-minute limit. Upload to S3 on save. Associate with `Grade` or `CriterionScore`. API: `POST /grades/{id}/media-comments`, `DELETE /media-comments/{id}`. |
| M4.11 | Video comment recording | Extend media comment to support webcam + optional screen share. Same storage and association model. |
| M4.12 | Media comment bank and export | Save media comment to reusable bank. Apply saved comment to new essay in one action. Include media link/QR code in PDF export. Access-controlled pre-signed URLs for playback. |

---

## M5 — Student Intelligence

> Persistent skill profiles, longitudinal tracking, class insights, and writing process visibility.

### Student Skill Profiles

| # | Issue Title | Description |
|---|---|---|
| M5.1 | **[BLOCKER]** Skill normalization layer | Configurable mapping from rubric criterion names to canonical skill dimensions (`thesis`, `evidence`, `organization`, `analysis`, `mechanics`, `voice`). Fuzzy match at grade-write time. Unmapped criteria stored under `other`. Mapping stored as config, not hardcoded. |
| M5.2 | `StudentSkillProfile` migration and model | Alembic migration. JSONB `skill_scores` column. Upsert logic. |
| M5.3 | Skill profile update Celery task | Triggered on grade lock. Load all locked criterion scores for student. Normalize to skill dimensions. Compute weighted average, trend direction, and data point count per skill. Upsert `StudentSkillProfile`. |
| M5.4 | Student profile API | `GET /students/{id}` with skill profile embedded. `GET /students/{id}/history` — all graded assignments chronologically. |
| M5.5 | Student profile UI | Skill radar or bar chart per dimension. Historical timeline of assignments with scores. Strengths and gaps callouts. Growth indicators (improved / regressed). Private teacher notes field. |

### Class Insights

| # | Issue Title | Description |
|---|---|---|
| M5.6 | Class insights API | `GET /classes/{id}/insights` — class average per skill dimension, score distributions, common issues aggregated from feedback. `GET /assignments/{id}/analytics` — per-assignment breakdown. |
| M5.7 | Skill heatmap UI | Grid: students as rows, skills as columns. Color-coded by score. Sortable by skill. Links to individual student profile. |
| M5.8 | Common issues and distribution UI | Ranked list of most-flagged issues across class with student counts. Histogram of score distribution per criterion. Outlier highlighting. Cross-assignment trend chart. |

### Writing Process Visibility

| # | Issue Title | Description |
|---|---|---|
| M5.9 | In-browser essay writing interface | Basic rich-text writing area within the assignment submission flow. Captures incremental changes (debounced saves every 10–15 seconds). Stores snapshots as JSONB in `essay_versions`. |
| M5.10 | Composition timeline and process signals | Parse snapshot history into session timeline. Detect: large paste events, rapid-completion events. Compute: session count, duration, inter-session gaps, active writing time. |
| M5.11 | Writing process visibility UI | Visual timeline in essay review interface. Session markers, paste event flags. Version snapshot viewer (view essay at any point in history). Process insight callout (e.g., "Written in a single 20-minute session"). |

---

## M6 — Prioritization & Instruction

> Teacher worklist, auto-grouping, instruction recommendations, and resubmission loop.

### Auto-Grouping

| # | Issue Title | Description |
|---|---|---|
| M6.1 | Auto-grouping Celery task | After each batch of grades is locked, compute skill groups from updated `StudentSkillProfile` records. Cluster students by shared underperforming skill dimensions. Apply minimum group size threshold. Store groups as JSONB on class or as a separate `student_groups` table. |
| M6.2 | Auto-grouping API | `GET /classes/{id}/groups` — current groups with student lists, shared skill gap labels, and group stability data (persistent / new / exited). |
| M6.3 | Auto-grouping UI | Group list view (name, skill gap, student count). Expand to see individual students. Manual adjust (add/remove student from group). Cross-reference link to class heatmap. |

### Teacher Worklist

| # | Issue Title | Description |
|---|---|---|
| M6.4 | Worklist generation logic | Compute worklist from student profiles: persistent gap (same group 2+ assignments), regression (score drop), high inconsistency, non-responder (no improvement after resubmission). Rank by urgency. Link each item to a suggested action from the instruction engine. |
| M6.5 | Worklist API | `GET /worklist`, `POST /worklist/{id}/complete`, `POST /worklist/{id}/snooze`, `DELETE /worklist/{id}`. |
| M6.6 | Worklist UI | Ranked list with urgency indicators. Reason and suggested action per student. Mark done / snooze / dismiss controls. Filter by action type, skill gap, urgency. Default to top 10, expand to full class. |

### Instruction Engine

| # | Issue Title | Description |
|---|---|---|
| M6.7 | Instruction recommendation generation | LLM-powered recommendation generation for: mini-lessons (objective, structure, example), targeted exercises (single-skill prompts), intervention suggestions (1:1, reading scaffolds, peer review). Triggered from worklist items or student profile gaps. Evidence summary included with each recommendation. |
| M6.8 | Instruction API | `POST /students/{id}/recommendations` — generate recommendation for a student gap. `POST /classes/{id}/groups/{groupId}/recommendations` — for a group. `POST /recommendations/{id}/assign` — teacher assigns exercise to student/group (explicit teacher action). |
| M6.9 | Instruction recommendations UI | Recommendation card: objective, structure, evidence summary. Accept / modify / dismiss controls. Assign exercise flow (teacher confirms before any action is applied to student record). |

### Resubmission Loop

| # | Issue Title | Description |
|---|---|---|
| M6.10 | Resubmission intake and versioning | `POST /essays/{id}/resubmit` — submit new version. Store as new `EssayVersion` linked to same `Essay`. Configurable per-assignment limit. |
| M6.11 | Resubmission grading and comparison | Re-run grading task on resubmission. Score delta per criterion vs. original. Detect whether specific feedback points were addressed in revision. Flag low-effort revisions (surface-level changes). |
| M6.12 | Resubmission UI | Side-by-side diff view (original vs. revised). Score delta display per criterion. Feedback-addressed indicators. Version history list. Improvement signal in student profile. |

---

## M7 — Closed Loop

> Automation agents and teacher copilot. Every prior milestone must be complete before starting this one.

### Automation Agents

| # | Issue Title | Description |
|---|---|---|
| M7.1 | Intervention agent | Background Celery task that scans student profiles on a schedule. Detects trigger conditions (persistent gap, regression, non-response). Prepares recommended action and adds to teacher worklist. Teacher approves or dismisses — nothing acts without confirmation. |
| M7.2 | Predictive insights | Detect early trajectory risk signals from skill profile trends (declining across 3+ assignments, persistent low score with no improvement). Surface as worklist item labeled as prediction. Include confidence indicator and supporting data points. |
| M7.3 | Teacher copilot — data query layer | LLM-backed query interface backed by real class data. Supports: "Who is falling behind on thesis?", "What should I teach tomorrow?", "Which students haven't improved since my last feedback?". Queries against live Postgres data. Returns ranked lists and summaries. Never fabricates — expresses uncertainty if data is insufficient. Security: strictly scoped to authenticated teacher's classes only. |
| M7.4 | Teacher copilot UI | Conversational input in sidebar or dedicated panel. Display structured response (ranked list, summary, or recommendation). Link-through to relevant students, assignments, or worklist items. No action taken from copilot — surfacing only. |

---

## MX — Cross-Cutting Issues (Any Milestone)

These issues can be worked in parallel with any milestone they support.

| # | Issue Title | Description |
|---|---|---|
| MX.1 | Security hardening | Implement all items in `security.md`: security response headers middleware, CORS allowlist, rate limiting middleware (Redis counters), RLS policies on all tenant-scoped tables, `pip-audit` in CI, `npm audit` in CI. |
| MX.2 | Error handling and observability | Global FastAPI exception handler. Structured JSON logging throughout backend and Celery workers. No PII in any log line. Health check endpoints on all services. Correlation IDs on all requests. |
| MX.3 | End-to-end tests (Playwright) | 5 critical E2E journeys: (1) login → class → students → rubric → assignment, (2) upload → auto-assign → grade batch → progress, (3) review → override score → edit feedback → lock, (4) export PDF ZIP → download, (5) view student profile across two assignments. |
| MX.4 | Accessibility audit | Keyboard navigation throughout. ARIA labels on interactive elements. Focus management in modals and panels. Color contrast compliance. Screen reader testing on grading interface. |
| MX.5 | `prompt_version` field on Grade | Add `prompt_version VARCHAR(20)` column to `grades` table via Alembic migration. Populate from `GRADING_PROMPT_VERSION` env var at grade-write time. |
