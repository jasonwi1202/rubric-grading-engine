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
| **M3** | Foundation | Core product: rubric builder, class/roster management, essay upload and ingestion, AI grading engine, human-in-the-loop review interface, and export. | 26 | ✅ Complete |
| **M4** | Workflow | Confidence scoring, academic integrity detection, regrade requests, and media (audio/video) feedback. | 12 | ✅ Complete |
| **M5** | Student Intelligence | Persistent student skill profiles, longitudinal tracking, class insights heatmap, and writing process visibility. | 11 | ✅ Complete |
| **M6** | Prioritization & Instruction | Auto-grouping by skill gap, teacher worklist, instruction engine recommendations, and resubmission loop. | 12 | ✅ Complete |
| **M7** | Closed Loop | Automation agents, predictive insights, and teacher copilot (conversational data interface). Requires all prior milestones. | 9 | ✅ Complete |
| **M8** | Polish & Hardening | Complete missing feature UIs (interventions, text comments), review UI/UX, refactor/upgrade components, database migration resilience, and final hardening. | 9 | 🔄 In Progress |
++ | **M8** | Polish & Hardening | Complete missing feature UIs (interventions, text comments), review UI/UX, refactor/upgrade components, database migration resilience, and final hardening. | 9 | ✅ Complete |
| **M9** | Production Readiness & Compliance | Monitoring, operational runbooks, security scanning, upload safety, and performance validation required for reliable Railway production deployment. | 7 | 🔄 Planned |
| **MX** | Cross-Cutting | Security hardening, observability, E2E tests, accessibility, and prompt version tracking. Can be worked in parallel with any milestone. | 5 | ✅ Complete |
| | **Total** | | **111** | |

> Note: Milestone counts are issue-specific only. MX runs in parallel with any milestone.

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

## M3 — Foundation ✅ Complete

> Best-in-class rubric-based grading with transparent, editable AI feedback. This milestone produces the core product.

### Database & Models

| # | Issue Title | Description |
|---|---|---|
| ~~M3.1~~ | ~~**[BLOCKER]** Write initial Alembic migration: core schema~~ | ✅ Done — PR #79. Tables: `users`, `classes`, `class_enrollments`, `students`, `rubrics`, `rubric_criteria`, `assignments`, `essays`, `essay_versions`, `grades`, `criterion_scores`, `audit_logs` with all relationships, indexes, and constraints. |

### Rubric Builder

| # | Issue Title | Description |
|---|---|---|
| ~~M3.2~~ | ~~Rubric CRUD API~~ | ✅ Done — PR #80. `GET/POST /rubrics`, `GET/PATCH/DELETE /rubrics/{id}`, `POST /rubrics/{id}/duplicate`; weight-sum validation; snapshot logic. |
| ~~M3.3~~ | ~~Rubric Builder UI~~ | ✅ Done — PR #81. Criterion list with add/edit/delete/reorder (drag-and-drop); weight indicator; save/cancel. |
| ~~M3.4~~ | ~~Rubric templates~~ | ✅ Done — PR #82. 3 system templates; personal template saving; template picker in builder and assignment creation. |

### Class & Student Management

| # | Issue Title | Description |
|---|---|---|
| ~~M3.5~~ | ~~Class CRUD API~~ | ✅ Done — PR #83. |
| ~~M3.6~~ | ~~Student & enrollment API~~ | ✅ Done — PR #84. |
| ~~M3.7~~ | ~~CSV roster import~~ | ✅ Done — PR #85. |
| ~~M3.8~~ | ~~Class and roster management UI~~ | ✅ Done — PR #86. |

### Essay Input & Ingestion

| # | Issue Title | Description |
|---|---|---|
| ~~M3.9~~ | ~~Essay upload API and file extraction~~ | ✅ Done — PR #87. |
| ~~M3.10~~ | ~~Student auto-assignment on upload~~ | ✅ Done — PR #88. |
| ~~M3.11~~ | ~~Essay input UI~~ | ✅ Done — PR #89. |

### Assignment Management

| # | Issue Title | Description |
|---|---|---|
| ~~M3.12~~ | ~~Assignment CRUD API~~ | ✅ Done — PR #90. Status state machine; rubric snapshot at creation. |
| ~~M3.13~~ | ~~Assignment UI~~ | ✅ Done — PR #91. |

### AI Grading Engine

| # | Issue Title | Description |
|---|---|---|
| ~~M3.14~~ | ~~**[BLOCKER]** LLM client and prompt infrastructure~~ | ✅ Done — PR #93. |
| ~~M3.15~~ | ~~Grading Celery task~~ | ✅ Done — PR #94. |
| ~~M3.16~~ | ~~Batch grading API and progress tracking~~ | ✅ Done — PR #95. |
| ~~M3.17~~ | ~~Batch grading UI~~ | ✅ Done — PR #96. |

### Feedback Generator

| # | Issue Title | Description |
|---|---|---|
| ~~M3.18~~ | ~~Feedback generation in grading task~~ | ✅ Done — PR #97. Per-criterion feedback, overall summary, tone parameter. |
| ~~M3.19~~ | ~~Comment bank API~~ | ✅ Done — PR #98. |

### Teacher Review & Control

| # | Issue Title | Description |
|---|---|---|
| ~~M3.20~~ | ~~Grade read and edit API~~ | ✅ Done — PR #99. Score override, feedback edit, lock; all edits audit-logged. |
| ~~M3.21~~ | ~~Essay review interface (core)~~ | ✅ Done — PR #101. Two-panel layout: essay text left, rubric scores + feedback right. Inline score override, feedback editor, lock grade button. |
| ~~M3.22~~ | ~~Review queue UI~~ | ✅ Done — PR #102. List view with status badges, sort/filter, keyboard nav, link-through to essay review. |
| ~~M3.23~~ | ~~Audit log API~~ | ✅ Done — PR #103. `GET /grades/{id}/audit` returns full change history with timestamps, actor, before/after values. |

### Export

| # | Issue Title | Description |
|---|---|---|
| ~~M3.24~~ | ~~Export API and Celery task~~ | ✅ Done — PR #104. Async PDF ZIP export via Celery; S3 storage; polling and pre-signed download URL. |
| ~~M3.25~~ | ~~CSV grade export~~ | ✅ Done — PR #105. Synchronous CSV export of all locked grades; LMS-compatible format. |
| ~~M3.26~~ | ~~Export UI~~ | ✅ Done — PR #106. Export button, PDF ZIP + CSV + clipboard options, async download flow. |

---

## M4 — Workflow ✅ Complete

> Confidence scoring, academic integrity, assignment workflow polish, regrade requests, and media feedback.

### Confidence Scoring

| # | Issue Title | Description |
|---|---|---|
| ~~M4.1~~ | ~~Confidence scoring in grading~~ | ✅ Done — PR #132. `confidence` field per criterion and `overall_confidence` on `Grade`. |
| ~~M4.2~~ | ~~Confidence-based review queue~~ | ✅ Done — PR #133. Low-confidence-first sort, fast-review filter, bulk-approve. |

### Academic Integrity

| # | Issue Title | Description |
|---|---|---|
| ~~M4.3~~ | ~~Add `IntegrityReport` migration and model~~ | ✅ Done — PR #134. |
| ~~M4.4~~ | ~~Internal cross-submission similarity~~ | ✅ Done — PR #135. pgvector embeddings, cosine similarity, flag pairs above threshold. |
| ~~M4.5~~ | ~~Third-party integrity API integration~~ | ✅ Done — PR #136. Abstract `IntegrityProvider`, configurable via `INTEGRITY_PROVIDER` env var, fails open to internal. |
| ~~M4.6~~ | ~~Integrity report API and UI~~ | ✅ Done — PR #137. `GET /essays/{id}/integrity`, status actions, integrity panel in review interface. |

### Regrade Requests

| # | Issue Title | Description |
|---|---|---|
| ~~M4.7~~ | ~~Regrade request data model and migration~~ | ✅ Done — PR #138. |
| ~~M4.8~~ | ~~Regrade request API~~ | ✅ Done — PR #139. Submission window enforcement, per-grade limit, resolve with audit log. |
| ~~M4.9~~ | ~~Regrade request UI~~ | ✅ Done — PR #140. Queue tab, log form, side-by-side review panel, approve/deny controls. |

### Media Feedback

| # | Issue Title | Description |
|---|---|---|
| ~~M4.10~~ | ~~Media comment recording and storage~~ | ✅ Done — PR #141. Audio via MediaRecorder, S3 upload, pre-signed URL playback. |
| ~~M4.11~~ | ~~Video comment recording~~ | ✅ Done — PR #142. Webcam + optional screen share. |
| ~~M4.12~~ | ~~Media comment bank and export~~ | ✅ Done — PR #143. Bank picker, apply to grade, QR code in PDF export. |

---

## M5 — Student Intelligence ✅ Complete

> Persistent skill profiles, longitudinal tracking, class insights, and writing process visibility.

### Student Skill Profiles

| # | Issue Title | Description |
|---|---|---|
| ~~M5.1~~ | ~~**[BLOCKER]** Skill normalization layer~~ | ✅ Done — PR #168. Configurable mapping from rubric criterion names to canonical skill dimensions (`thesis`, `evidence`, `organization`, `analysis`, `mechanics`, `voice`). Fuzzy match at grade-write time. Unmapped criteria stored under `other`. Mapping stored as config, not hardcoded. |
| ~~M5.2~~ | ~~`StudentSkillProfile` migration and model~~ | ✅ Done — PR #169. Alembic migration. JSONB `skill_scores` column. Upsert logic. |
| ~~M5.3~~ | ~~Skill profile update Celery task~~ | ✅ Done — PR #170. Triggered on grade lock. Load all locked criterion scores for student. Normalize to skill dimensions. Compute weighted average, trend direction, and data point count per skill. Upsert `StudentSkillProfile`. |
| ~~M5.4~~ | ~~Student profile API~~ | ✅ Done — PR #171. `GET /students/{id}` with skill profile embedded. `GET /students/{id}/history` — all graded assignments chronologically. |
| ~~M5.5~~ | ~~Student profile UI~~ | ✅ Done — PR #172. Skill radar or bar chart per dimension. Historical timeline of assignments with scores. Strengths and gaps callouts. Growth indicators (improved / regressed). Private teacher notes field. |

### Class Insights

| # | Issue Title | Description |
|---|---|---|
| ~~M5.6~~ | ~~Class insights API~~ | ✅ Done — PR #173. `GET /classes/{id}/insights` — class average per skill dimension, score distributions, common issues aggregated from feedback. `GET /assignments/{id}/analytics` — per-assignment breakdown. |
| ~~M5.7~~ | ~~Skill heatmap UI~~ | ✅ Done — PR #174. Grid: students as rows, skills as columns. Color-coded by score. Sortable by skill. Links to individual student profile. |
| ~~M5.8~~ | ~~Common issues and distribution UI~~ | ✅ Done — PR #175. Ranked list of most-flagged issues across class with student counts. Histogram of score distribution per criterion. Outlier highlighting. Cross-assignment trend chart. |

### Writing Process Visibility

| # | Issue Title | Description |
|---|---|---|
| ~~M5.9~~ | ~~In-browser essay writing interface~~ | ✅ Done — PR #176. Basic rich-text writing area within the assignment submission flow. Captures incremental changes (debounced saves every 10–15 seconds). Stores snapshots as JSONB in `essay_versions`. |
| ~~M5.10~~ | ~~Composition timeline and process signals~~ | ✅ Done — PR #177. Parse snapshot history into session timeline. Detect: large paste events, rapid-completion events. Compute: session count, duration, inter-session gaps, active writing time. |
| ~~M5.11~~ | ~~Writing process visibility UI~~ | ✅ Done — PR #178. Visual timeline in essay review interface. Session markers, paste event flags. Version snapshot viewer (view essay at any point in history). Process insight callout (e.g., "Written in a single 20-minute session"). |

---

## M6 — Prioritization & Instruction ✅ Complete

> Teacher worklist, auto-grouping, instruction recommendations, and resubmission loop.

### Auto-Grouping

| # | Issue Title | Description |
|---|---|---|
| ~~M6.1~~ | ~~Auto-grouping Celery task~~ | ✅ Done — PR #197. After each batch of grades is locked, compute skill groups from updated `StudentSkillProfile` records. Cluster students by shared underperforming skill dimensions. Apply minimum group size threshold. Store groups in `student_groups` table. |
| ~~M6.2~~ | ~~Auto-grouping API~~ | ✅ Done — PR #198. `GET /classes/{id}/groups` — current groups with student lists, shared skill gap labels, and group stability data (persistent / new / exited). |
| ~~M6.3~~ | ~~Auto-grouping UI~~ | ✅ Done — PR #199. Group list view (name, skill gap, student count). Expand to see individual students. Manual adjust (add/remove student from group). Cross-reference link to class heatmap. |

### Teacher Worklist

| # | Issue Title | Description |
|---|---|---|
| ~~M6.4~~ | ~~Worklist generation logic~~ | ✅ Done — PR #200. Compute worklist from student profiles: persistent gap (same group 2+ assignments), regression (score drop), high inconsistency, non-responder (no improvement after resubmission). Rank by urgency. |
| ~~M6.5~~ | ~~Worklist API~~ | ✅ Done — PR #201. `GET /worklist`, `POST /worklist/{id}/complete`, `POST /worklist/{id}/snooze`, `DELETE /worklist/{id}`. |
| ~~M6.6~~ | ~~Worklist UI~~ | ✅ Done — PR #202. Ranked list with urgency indicators. Reason and suggested action per student. Mark done / snooze / dismiss controls. Filter by action type, skill gap, urgency. Default to top 10, expand to full class. |

### Instruction Engine

| # | Issue Title | Description |
|---|---|---|
| ~~M6.7~~ | ~~Instruction recommendation generation~~ | ✅ Done — PR #203. LLM-powered recommendation generation for: mini-lessons (objective, structure, example), targeted exercises (single-skill prompts), intervention suggestions (1:1, reading scaffolds, peer review). Triggered from worklist items or student profile gaps. Evidence summary included with each recommendation. |
| ~~M6.8~~ | ~~Instruction API~~ | ✅ Done — PR #205. `POST /students/{id}/recommendations` — generate recommendation for a student gap. `POST /classes/{id}/groups/{groupId}/recommendations` — for a group. `POST /recommendations/{id}/assign` — teacher assigns exercise to student/group (explicit teacher action). |
| ~~M6.9~~ | ~~Instruction recommendations UI~~ | ✅ Done — PR #206. Recommendation card: objective, structure, evidence summary. Accept / modify / dismiss controls. Assign exercise flow (teacher confirms before any action is applied to student record). |

### Resubmission Loop

| # | Issue Title | Description |
|---|---|---|
| ~~M6.10~~ | ~~Resubmission intake and versioning~~ | ✅ Done — PR #207. `POST /essays/{id}/resubmit` — submit new version. Store as new `EssayVersion` linked to same `Essay`. Configurable per-assignment limit. |
| ~~M6.11~~ | ~~Resubmission grading and comparison~~ | ✅ Done — PR #208. Re-run grading task on resubmission. Score delta per criterion vs. original. Detect whether specific feedback points were addressed in revision. Flag low-effort revisions (surface-level changes). |
| ~~M6.12~~ | ~~Resubmission UI~~ | ✅ Done — PR #209. Side-by-side diff view (original vs. revised). Score delta display per criterion. Feedback-addressed indicators. Version history list. Improvement signal in student profile. |

---

## M7 — Closed Loop ✅ Complete

> Automation agents and teacher copilot. Every prior milestone must be complete before starting this one.

### Automation Agents

| # | Issue Title | Description |
|---|---|---|
| ~~M7.1~~ | ~~Intervention agent~~ | ✅ Done — PR #221. Scheduled intervention scan task, intervention recommendations API, teacher approve/dismiss lifecycle, audit logging. |
| ~~M7.2~~ | ~~Predictive insights~~ | ✅ Done — PR #222. Trajectory-risk predictive worklist signal with confidence indicator and supporting trend data. |
| ~~M7.3~~ | ~~Teacher copilot — data query layer~~ | ✅ Done — PR #223. Teacher-scoped copilot query API backed by live Postgres data with uncertainty handling and schema-validated LLM responses. |
| ~~M7.4~~ | ~~Teacher copilot UI~~ | ✅ Done — PR #224. Dedicated `/dashboard/copilot` conversational panel with class scoping and structured response rendering. |

---

## M8 — Polish & Hardening 🔄 In Progress
++ ## M8 — Polish & Hardening ✅ Complete

> Complete missing feature UIs, review all component implementations for correctness, improve visual design and UX, ensure clean database migrations, and final hardening. This milestone focuses on quality, completeness, and resilience rather than new features.

### Missing Feature UIs

| # | Issue Title | Description |
|---|---|---|
| M8.1 | Build interventions page UI | Backend API exists (`/interventions` CRUD). Build a `/dashboard/interventions` page that lists pending recommendations, lets teachers approve/dismiss them with notes, shows approval history, and integrates with class worklist. |
++ | ~~M8.1~~ | ~~Build interventions page UI~~ | ✅ Done — PR #237. `/dashboard/interventions` page with list, approve/dismiss controls, notes, and approval history. |
| M8.2 | Build text comment-bank UI | Backend API exists (`/comment-bank` CRUD and suggestions). Build a UI for teachers to manage reusable text feedback snippets within the review panel: save comments to bank, search/suggest, apply to grades (like media comment bank already does). |
++ | ~~M8.2~~ | ~~Build text comment-bank UI~~ | ✅ Done — PR #238. `TextCommentBankPicker` in review panel: save, search/suggest, apply. |
| M8.3 | Migrate BrowserWritingInterface to Selection/Range API | Currently uses deprecated `document.execCommand`. Migrate to modern Selection/Range API or adopt maintained library (e.g., TipTap) for text formatting (bold, italic, underline, etc.) in the browser composition interface. |
++ | ~~M8.3~~ | ~~Migrate BrowserWritingInterface to Selection/Range API~~ | ✅ Done — PR #239. Bold/Italic/Underline migrated from `document.execCommand` to Selection/Range API. |
| M8.4 | Add deterministic export failure injection for E2E | Expose a test-mode toggle in the backend (via env or config) that allows Playwright tests to inject deterministic failures into the export Celery task. Enable E2E test: `export failure + retry UX using deterministic backend failure`. |
++ | ~~M8.4~~ | ~~Add deterministic export failure injection for E2E~~ | ✅ Done — PR #240. `EXPORT_TASK_FORCE_FAIL` env var; `POST /debug/export-task/arm-failure` gated by `TESTING_MODE=true`. |
| M8.5 | Add deterministic short-lived token mode for E2E | Expose a test-mode endpoint or config that lets Playwright tests generate access tokens with very short TTL (seconds). Enable E2E test: `auth silent-refresh real expiry path with deterministic token expiration`. |
++ | ~~M8.5~~ | ~~Add deterministic short-lived token mode for E2E~~ | ✅ Done — PR #241. `POST /debug/short-lived-token` issues sub-30s TTL tokens when `TESTING_MODE=true`. |

### Quality & UX Review

| # | Issue Title | Description |
|---|---|---|
| M8.6 | UI component implementation review | Audit all React components in `components/` for correct hook usage, proper accessibility (ARIA labels, roles, focus management), consistent prop interfaces, and correct error boundary placement. Document or refactor any components that violate React patterns or shadcn/ui conventions. |
++ | ~~M8.6~~ | ~~UI component implementation review~~ | ✅ Done — PR #244. Error boundaries audited and corrected; `ProgressBar` a11y attributes fixed; hook usage reviewed across all components. |
| M8.7 | Visual design & brand review | Review the entire UI (public site, dashboard, modals, forms) against educational product standards. Check: color contrast, typography hierarchy, spacing consistency, responsive design, icon usage, and alignment with a professional K-12 ed-tech aesthetic. Refine CSS/Tailwind where needed. |
++ | ~~M8.7~~ | ~~Visual design & brand review~~ | ✅ Done — PR #249. Mobile nav contrast, iconography polish, sidebar spacing, and responsive design reviewed and corrected. |
| M8.8 | Database migration resilience | Audit all Alembic migrations for: zero-downtime patterns, reversibility on rollback, data safety (no data loss or corruption), idempotency, and documentation of breaking changes. Ensure migrations can be applied/rolled back cleanly in production. Document any edge cases or manual steps required. |
++ | ~~M8.8~~ | ~~Database migration resilience~~ | ✅ Done — PR #250. All 33 Alembic revisions audited; roundtrip upgrade/downgrade validated; zero-downtime patterns confirmed. |
| M8.9 | Final security & error handling pass | Review all error messages (never log PII), all API responses (match `{"data": ...}` envelope), all auth checks (401 vs 403 vs 404 semantics), all tenant isolation (teacher_id in WHERE clause), and all LLM prompts (essay in user role, injection defense present). Verify no hardcoded secrets, credentials, or student data in source. |
++ | ~~M8.9~~ | ~~Final security & error handling pass~~ | ✅ Done — PR #251. All error messages, response envelopes, auth semantics, tenant isolation, and LLM prompt roles verified. No hardcoded secrets or student data found. |

---

## M9 — Production Readiness & Compliance 🔄 Planned

> Close the final operational and compliance gaps before Railway production launch. This milestone is deployment-focused: reliability, security posture, incident readiness, and performance confidence.

### Must-Have Before Production

| # | Issue Title | Description |
|---|---|---|
| M9.1 | Monitoring and alerting baseline | Add production metrics and alerting for API availability, worker queue depth, error rate, and latency. Include practical thresholds and escalation targets. |
| M9.2 | Operational runbook and incident response | Write a concrete runbook for on-call operation: common failures, investigation steps, rollback triggers, comms templates, and incident timeline/checklist. |
| M9.3 | File upload malware scanning | Add scanning (e.g., ClamAV or equivalent managed service) for uploaded PDF/DOCX/TXT files before they are processed for extraction/grading. |
| M9.4 | CI security scanning expansion | Add automated AppSec checks in CI (e.g., OWASP dependency checks and Python static security scanning) and define fail gates for high/critical findings. |
| M9.5 | Load and performance validation | Add repeatable load tests that validate key targets in `docs/architecture/performance.md` (grading throughput, p95 latencies, queue drain behavior). |

### Nice-to-Have Shortly After Launch

| # | Issue Title | Description |
|---|---|---|
| M9.6 | Feature flag framework | Introduce feature flags for high-risk or in-progress features so production rollout can be gradual and reversible without hotfix deploys. |
| M9.7 | APM and distributed tracing | Add APM/tracing to connect request latency, DB spans, Celery tasks, and third-party calls for faster root-cause analysis in production incidents. |

---

## MX — Cross-Cutting Issues (Any Milestone)

These issues can be worked in parallel with any milestone they support.

| # | Issue Title | Description |
|---|---|---|
| ~~MX.1~~ | ~~Security hardening~~ | ✅ Done — PR #144. Security headers middleware, CORS wildcard rejection, rate limiting, RLS on all tenant tables, pip-audit + npm audit in CI. |
| ~~MX.2~~ | ~~Error handling and observability~~ | ✅ Done — PR #145. Structured JSON logging, correlation IDs, enhanced health check. |
| ~~MX.3a~~ | ~~E2E Journey 1 — Login, class, rubric, assignment~~ | ✅ Done — PR #146. |
| ~~MX.3b~~ | ~~E2E Journey 2 — Upload, auto-assign, batch grade~~ | ✅ Done — PR #147. |
| ~~MX.3c~~ | ~~E2E Journey 3 — Review, override, lock~~ | ✅ Done — PR #148. |
| ~~MX.3d~~ | ~~E2E Journey 4 — Export PDF ZIP and CSV~~ | ✅ Done — PR #149. |
| ~~MX.3e~~ | ~~E2E Journey 5 — Student profile across two assignments~~ | ✅ Done — PR #179. |
| ~~MX.4~~ | ~~Accessibility audit~~ | ✅ Done — PR #150. axe-core Playwright scan in CI, ARIA labels, focus management, WCAG 2.1 AA contrast. |
| ~~MX.5~~ | ~~`prompt_version` field on Grade~~ | ✅ Done — PR #151. |
