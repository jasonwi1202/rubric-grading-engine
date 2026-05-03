# Changelog

All notable changes to this project are documented here. This file is updated automatically by the `milestone-release.yml` workflow when a release branch is merged to `main`, and manually for hotfixes.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versions follow `v0.{milestone+1}.0` (e.g. M0 → v0.1.0, M1 → v0.2.0).

---

## [Unreleased]

No unreleased changes on `release/m7` beyond the release-finalization checklist PR.

---

## [v0.8.0] — M7 Closed Loop — Unreleased (pending merge to main)

### Added
- **Intervention agent** — scheduled background scan over `StudentSkillProfile` data to create teacher-reviewed `intervention_recommendations`; trigger types include `persistent_gap`, `regression`, and `non_responder`; teachers explicitly approve or dismiss recommendations before any follow-up action is taken
- **Intervention API** — `GET /interventions`, `POST /interventions/{id}/approve`, `DELETE /interventions/{id}` with non-enumerable `404` behavior for inaccessible rows and full audit logging of creation / approval / dismissal
- **Predictive trajectory risk signal** — worklist generation now emits `trajectory_risk` items when recent assignment-over-assignment scores show a consistent downward trend before a confirmed regression; items carry confidence level and supporting decline data
- **Teacher copilot data query layer** — `POST /copilot/query` answers natural-language instructional questions from live teacher-scoped Postgres data (skill profiles + worklist signals), resolves student display names after parsing, and expresses uncertainty when data is sparse instead of fabricating
- **Teacher copilot UI** — dedicated `/dashboard/copilot` conversational panel with optional class scope selector, structured ranked-list / summary rendering, and read-only notice; responses link to student profiles via UUID-only URLs and never take autonomous action
- **Demo-ready M7 seed data** — demo seed now includes a `trajectory_risk` worklist item, a pending intervention recommendation, and deterministic fake-LLM copilot responses so M7 can be demonstrated without an OpenAI key
- **M7 demo smoke coverage** — `scripts/smoke_test_demo.py` now validates seeded trajectory-risk worklist data, intervention recommendations, and the teacher copilot endpoint
- **M7 E2E coverage** — Playwright journey for the teacher copilot conversational UI, plus E2E hardening for essay upload strict-mode and M4 login hydration timing

### Security
- Copilot remains read-only: no grade changes, assignments, or interventions occur from the copilot UI without explicit teacher action elsewhere
- No student names are sent to the LLM in the copilot context; only UUIDs and aggregate skill/worklist data are provided, and names are resolved after response parsing
- Copilot query input is validated server-side and client-side for non-blank content; invalid request bodies return `422 VALIDATION_ERROR`
- Copilot UI student-profile links no longer include student display names in accessible labels; the link uses a generic aria-label to avoid leaking PII in accessibility metadata

### Tests added
- Backend unit: `test_intervention_agent_service`, `test_intervention_router`, `test_intervention_task`, `test_copilot_service`, `test_copilot_router`, extended `test_worklist_service`, and parser coverage in `test_llm_parsers`
- Backend integration: `test_interventions`, `test_copilot`
- Frontend unit: `copilot-panel.test.tsx`, extended `worklist-panel.test.tsx`
- Frontend E2E: teacher copilot journey plus hardening updates to existing M3/M4 workflows

---

## [v0.7.0] — M6 Prioritization & Instruction — Unreleased (pending merge to main)

### Added
- **Auto-grouping by skill gap** — after each grading batch, a Celery task clusters students into small groups based on shared underperforming skill dimensions derived from `StudentSkillProfile`; minimum group size and score threshold are configurable; groups stored in new `student_groups` table with stability tracking (`new`/`persistent`/`exited`)
- **Auto-grouping API** — `GET /classes/{id}/groups` returns current groups with student lists, skill-gap labels, and stability; `PATCH /classes/{id}/groups/{groupId}` allows manual membership adjustment
- **Auto-grouping UI** — Groups tab on class page: expandable group cards with student list, skill badge, stability indicator; add/remove student from group; cross-reference link to class heatmap
- **Teacher worklist** — `GET /worklist` returns a ranked list of students requiring attention, derived from skill profiles and group history; trigger conditions: persistent gap (same group 2+ assignments), score regression, high inconsistency, non-responder (no improvement after resubmission); urgency-ranked
- **Worklist API** — `POST /worklist/{id}/complete`, `POST /worklist/{id}/snooze`, `DELETE /worklist/{id}`; filter by trigger type, skill, urgency
- **Worklist UI** — ranked list view with urgency indicators; reason and suggested action per item; mark done / snooze / dismiss controls; filter bar; default top-10 with expand-all
- **Instruction recommendation generation** — `POST /students/{id}/recommendations` and `POST /classes/{id}/groups/{groupId}/recommendations` call a versioned LLM prompt (`instruction-v1`) to produce mini-lesson, targeted exercise, and intervention recommendations; evidence summary included with each recommendation; LLM response validated before any DB write; prompt version stored on every `instruction_recommendations` row
- **Instruction API** — `GET /students/{id}/recommendations`; `POST /recommendations/{id}/assign` — explicit teacher action required before any exercise is associated with a student record
- **Instruction recommendations UI** — recommendation card with objective, evidence summary, strategy type, estimated time; accept / modify / dismiss controls; assign-exercise confirmation modal (teacher must explicitly confirm)
- **Resubmission intake and versioning** — `POST /essays/{id}/resubmit` creates a new `EssayVersion` linked to the same `Essay`; per-assignment limit configurable via `RESUBMISSION_LIMIT`; re-grading triggered automatically via Celery; new unique constraint on `(essay_id, version_number)`
- **Resubmission grading and comparison** — `GET /essays/{id}/revision-comparison` returns criterion-level score deltas, flags for which feedback points were addressed in the revision, and a low-effort flag when content change ratio is below threshold; criterion comparison uses a versioned revision LLM prompt (`revision-v1`)
- **Resubmission UI** — side-by-side diff view (original vs. revised text); score delta display per criterion; feedback-addressed indicators; version history list; improvement signal fed back into student profile
- **E2E Journey 6** — Playwright: login → grade batch → groups tab populated → worklist item appears → mark item done (Closes MX.6b)
- **E2E Journey 7** — Playwright: submit essay → grade → resubmit → comparison view → score delta visible (Closes MX.7b)
- **RLS and tenant isolation for all M6 tables** — `student_groups`, `teacher_worklist_items`, `instruction_recommendations`, and `revision_comparisons` all have Row Level Security enabled and are verified by `tests/integration/test_m6_tenant_isolation.py`

### Security
- All four new tables have PostgreSQL RLS policies restricting access to the owning `teacher_id`; application layer enforces `teacher_id` in every query as defense-in-depth
- Instruction recommendation and revision prompts keep essay content strictly in the `user` role; system prompts contain the standard injection-defense directive
- `instruction_recommendations` rows store `prompt_version` to enable auditing of which prompt version produced each recommendation
- `revision_comparisons` receives sanitized diffs; raw essay text is never placed in the system role
- No student PII in any log line added in M6; only entity IDs (`essay_id`, `student_id`, `group_id`) used in logger calls

### Tests added
- Backend unit: `test_auto_grouping_api`, `test_worklist_service`, `test_worklist_router`, `test_instruction_recommendation_service`, `test_instruction_recommendation_router`, `test_resubmission_service`, `test_essay_service`, extended `test_tenant_isolation`
- Backend integration: `test_m6_tenant_isolation` (RLS assertions on all new tables), `test_resubmission` (full flow against real Postgres), `test_instruction_recommendations`
- Frontend unit: `recommendation-panel.test.tsx`, `resubmission-panel.test.tsx`
- E2E: Journey 6 (`mx6b-journey6-worklist-auto-grouping.spec.ts`), Journey 7 (`mx7b-resubmission-loop.spec.ts`)

---

## [v0.6.0] — M5 Student Intelligence — Unreleased (pending merge to main)

### Added
- **Skill normalization layer** — configurable JSON mapping from teacher-entered rubric criterion names to seven canonical skill dimensions (`thesis`, `evidence`, `organization`, `analysis`, `mechanics`, `voice`, `other`); fuzzy matching via `rapidfuzz` token-set ratio (default threshold: 80); unmapped criteria stored under `other`; overridable via `SKILL_NORMALIZATION_CONFIG_PATH` env var without code changes
- **`StudentSkillProfile` model and migration** — new `student_skill_profiles` table; `skill_scores JSONB` stores per-dimension `final_score`, `trend`, and `data_point_count`; unique on `(student_id, teacher_id)`; upserted on every grade lock
- **Skill profile update Celery task** — triggered automatically when a grade is locked; normalizes all locked criterion scores to skill dimensions; computes recency-weighted average; detects trend direction (improving/declining/stable); upserts `StudentSkillProfile`
- **Student profile API** — `GET /students/{id}` now embeds `skill_profile` and `teacher_notes`; `GET /students/{id}/history` returns all graded assignments chronologically with per-criterion scores; `PATCH /students/{id}` accepts `teacher_notes`
- **Student profile UI** — skill bar chart per dimension; assignment history timeline; strengths and gaps callout cards; growth indicators (improving/declining/stable); private teacher notes field with save confirmation
- **Class insights API** — `GET /classes/{id}/insights` returns class average per skill dimension, score distributions, and common feedback issues ranked by frequency; `GET /assignments/{id}/analytics` returns per-assignment breakdown
- **Skill heatmap UI** — class grid (students × skill dimensions), color-coded by normalized score, sortable by any skill column, links to individual student profiles
- **Common issues and distribution UI** — ranked feedback-phrase list with student counts; score distribution histogram per criterion; cross-assignment trend chart for class averages
- **In-browser essay writing interface** — rich-text writing area with debounced autosave (10 s); paste sanitization (strips `<script>`, event handlers, tracking pixels); word count display; cancel/submit flow; snapshots stored as JSONB in `essay_versions`
- **Composition timeline and process signals** — snapshot history parsed into sessions; detects large paste events and rapid-completion events; computes session count, duration, inter-session gaps, and active writing time
- **Writing process visibility UI** — visual session timeline in essay review interface; paste-event flags; snapshot viewer (read essay at any saved point); process insight callout (e.g., "Written in a single 20-minute session")
- **E2E Journey 5** — Playwright: teacher locks grades across two assignments → student profile renders skill scores → skill history chart shows trend → strengths/gaps callouts match data (Closes MX.3e)

### Security
- `StudentSkillProfile` queries always include `teacher_id` in WHERE clause — no cross-teacher profile access possible
- Essay snapshot content never emitted in log lines; only `essay_id` and operation type logged
- Browser writing interface sanitizes pasted HTML before snapshot is saved or submitted
- `teacher_notes` never surfaced on any student-facing code path (no student-facing UI exists)

### Tests added
- Backend: `test_skill_normalization` (mapping, fuzzy match, custom config), `test_student_skill_profile` (weighted average, trend, clamping, upsert), `test_skill_profile_task` (Celery task, lock trigger, multi-assignment), `test_class_insights_service`, `test_composition_timeline` (session detection, paste detection, active-writing-time), `test_student_service` (profile embed, history, notes PATCH), `test_browser_compose` (snapshot save/fetch, word count)
- Frontend: `student-profile`, `skill-heatmap`, `class-insights-panel`, `writing-process-panel`, `browser-writing-interface` Vitest suites
- E2E: Journey 5 Playwright spec (`student-profile.spec.ts`)

---

## [v0.5.0] — M4 Workflow — Unreleased (pending merge to main)

### Added
- **Confidence scoring** — grading prompt extended to output `confidence` per criterion (`high`/`medium`/`low`); `CriterionScore.confidence` and `Grade.overall_confidence` stored; confidence badge in review queue; low-confidence-first sort; fast-review filter; bulk-approve for high-confidence essays (teacher-explicit, never automatic); per-criterion plain-language confidence explanation in review panel
- **Academic integrity — internal similarity** — essay embeddings computed via OpenAI embeddings API on upload (stored as `vector(1536)` in `essay_versions` via pgvector); cosine similarity queried against same-assignment essays; pairs above `INTEGRITY_SIMILARITY_THRESHOLD` flagged as `IntegrityReport` with `provider=internal`
- **Academic integrity — third-party provider** — abstract `IntegrityProvider` interface; `OriginalityAiProvider` / `WinstonAiProvider` (configurable via `INTEGRITY_PROVIDER` env var); fails open to internal provider on network error; `IntegrityReport` written by whichever provider runs
- **Academic integrity — API and UI** — `GET /essays/{id}/integrity`; `PATCH /integrity-reports/{id}/status` (`reviewed_clear`/`flagged`); per-essay integrity panel in review interface (AI likelihood indicator, similarity score, flagged passages highlighted); class-level flagged/clear/pending count on assignment page; all language framed as signals, not findings
- **Regrade requests** — `POST /grades/{id}/regrade-requests`; configurable submission window (`REGRADE_WINDOW_DAYS`) and per-grade limit (`REGRADE_MAX_PER_GRADE`); `GET /assignments/{id}/regrade-requests` queue; `POST /regrade-requests/{id}/resolve` (approve with optional new score / deny with required note); resolution audit-logged; regrade queue tab on assignment page; side-by-side review panel with approve/deny controls
- **Audio feedback comments** — in-browser audio recording via MediaRecorder API (max 3 min); uploaded to S3 at `media/{teacher_id}/{grade_id}/{uuid}.webm`; `POST /grades/{id}/media-comments`; `DELETE /media-comments/{id}`; access-controlled pre-signed URL playback; no student PII in S3 key
- **Video feedback comments** — webcam recording with optional screen share via `getDisplayMedia`; same S3 upload and API flow as audio; graceful degradation when camera permission denied
- **Media comment bank** — save-to-bank action; bank picker in review panel; apply saved comment to any grade in one click; media link / QR code included in PDF batch export
- **Security hardening** — `SecurityHeadersMiddleware` adds `X-Frame-Options`, `X-Content-Type-Options`, `Strict-Transport-Security`, `X-XSS-Protection` on every response; `RateLimitMiddleware` enforces per-IP Redis counters on `/auth/login`, `/auth/refresh`, `/auth/signup`; `CORS_ORIGINS` wildcard rejected at startup; PostgreSQL RLS enabled on all tenant-scoped tables (essays, grades, rubrics, assignments, classes, students, integrity reports, regrade requests, media comments); `pip-audit` and `npm audit` added to CI with failure on high/critical CVEs
- **Structured observability** — `CorrelationIdMiddleware` generates per-request UUIDs propagated to all log lines and Celery tasks; structured JSON logging via `logging_config.py` (timestamp, level, correlation_id, service, entity IDs — no PII); enhanced `/api/v1/health` returns dependency status for DB, Redis, S3; Celery task failure logging uses `error_type=type(exc).__name__` only
- **E2E test suite (Journeys 1–4)** — Playwright: Journey 1 (login → class → students → rubric → assignment); Journey 2 (upload → auto-assign → batch grade → progress); Journey 3 (review → override score → edit feedback → lock, HITL guarantee); Journey 4 (export PDF ZIP → download); shared `helpers.ts` fixture infrastructure; all test data seeded and torn down via API; LLM mocked at environment level
- **Accessibility audit** — `@axe-core/playwright` scan in CI; ARIA labels on all icon-only buttons, score inputs, status badges; focus management in all modals (focus in, trap, Escape, return to trigger); keyboard navigation throughout dashboard; WCAG 2.1 AA color contrast compliance
- **`prompt_version` on Grade** — `prompt_version VARCHAR(20) NOT NULL DEFAULT 'v1'` added to `grades` table; populated from `GRADING_PROMPT_VERSION` env var at grade-write time; included in `GET /essays/{id}/grade` response

### Security
- Rate limiting middleware on all auth endpoints (Redis counters, IP-keyed)
- CORS wildcard rejection enforced at application startup via Pydantic settings validator
- RLS policies on all tenant-scoped tables — dual enforcement at service layer and DB layer
- Academic integrity language deliberately framed as signals; no automated conclusions presented to teacher
- Media S3 keys contain no student PII; pre-signed URLs scoped to owning teacher with configurable TTL

### Fixed
- Auth router unit tests exhausting rate-limit counter across test runs — `_RATE_LIMIT_RULES` patched to `[]` in test module via `autouse` monkeypatch fixture
- `frontend/app/(onboarding)/onboarding/class/page.tsx` and `frontend/tests/unit/onboarding-class-page.test.tsx` saved as UTF-16 during conflict resolution — re-encoded as UTF-8 without BOM

### Tests added
- Backend: confidence schema validation, confidence derivation, integrity report model, embedding task (OpenAI mocked), integrity service provider selection, integrity router tenant isolation, regrade request model, regrade API enforcement (window, limit, resolve), regrade router, media comment service and router, security middleware header assertions, rate limit middleware (Redis mocked), RLS migration structure, logging config (no-PII assertions), tenant isolation cross-teacher 403 coverage
- Frontend: `confidence-review-queue`, `integrity-panel`, `regrade-queue`, `audio-recorder`, `video-recorder`, `media-bank-picker` Vitest component suites
- E2E: four Playwright journeys; `@axe-core/playwright` accessibility suite

---

## [v0.4.0] — M3 Foundation — Unreleased (pending merge to main)

### Added
- **Core database schema** — Alembic migration creating all grading tables: `users`, `classes`, `class_enrollments`, `students`, `rubrics`, `rubric_criteria`, `assignments`, `essays`, `essay_versions`, `grades`, `criterion_scores`, `audit_logs` with full relationships, indexes, and foreign key constraints
- **Rubric CRUD API** — `GET/POST /rubrics`, `GET/PATCH/DELETE /rubrics/{id}`, `POST /rubrics/{id}/duplicate`; weight-sum validation (must equal 100%); rubric snapshot logic (snapshot written at assignment creation, never mutated)
- **Rubric Builder UI** — drag-and-drop criterion reordering; per-criterion name, description, weight, min/max score, anchor text; live weight-sum indicator; save/cancel flow
- **Rubric templates** — 3 system-provided starter templates (5-paragraph essay, argumentative, research paper); teacher personal template saving; template picker in builder and assignment creation flow
- **Class CRUD API** — `GET/POST /classes`, `GET/PATCH /classes/{id}`, `POST /classes/{id}/archive`; scoped to authenticated teacher; academic year field
- **Student & enrollment API** — `GET/POST /classes/{id}/students`, `DELETE /classes/{id}/students/{studentId}`, `GET/PATCH /students/{id}`; student persistence model independent of classes; `ClassEnrollment` join table with soft removal
- **CSV roster import** — `POST /classes/{id}/students/import`; parses `full_name` and `external_id` columns; duplicate detection; returns diff (new / updated / skipped) for teacher confirmation before committing
- **Class and roster management UI** — class creation form; roster list view; add student manually; CSV import flow with diff confirmation screen; soft-remove student
- **Essay upload API** — `POST /assignments/{id}/essays` multipart upload; MIME validation via `python-magic`; size limit enforced; raw file stored to S3; text extracted from PDF (`pdfplumber`), DOCX (`python-docx`), TXT; word count computed; `Essay` + `EssayVersion` records created
- **Student auto-assignment on upload** — fuzzy match of essay filename, DOCX author metadata, and header text against class roster; auto-assigns when confidence ≥ 0.85 and single match; unmatched go to unassigned queue; name collisions flagged
- **Essay input UI** — single and multi-file drag-and-drop upload; upload progress; auto-assignment results review screen with manual correction before proceeding
- **Assignment CRUD API** — `GET/POST /classes/{id}/assignments`, `GET/PATCH /assignments/{id}`; full status state machine (`draft → open → grading → review → complete → returned`); rubric snapshot written at creation time; immutable after grading starts
- **Assignment UI** — assignment creation form (title, prompt, rubric picker, due date); assignment overview page with per-student submission status badges; status transition controls
- **LLM client and prompt infrastructure** — `llm/client.py` OpenAI wrapper with retry, timeout, and error normalization; versioned prompt templates in `llm/prompts/`; **prompt injection defense**: essay content always in `user` role, system prompt instructs model to ignore directives found in essay text; essay text delimited with `<ESSAY_START>` / `<ESSAY_END>` tags
- **Grading Celery task** — `grade_essay` task loads essay text + rubric snapshot + strictness config; constructs versioned grading prompt; calls LLM; validates structured response schema; writes `Grade` + `CriterionScore` records; handles all failure modes (parse error, missing criterion, out-of-range score, timeout); scores server-side clamped to `[min_score, max_score]`
- **Batch grading API and Redis progress tracking** — `POST /assignments/{id}/grade` enqueues one task per essay, returns 202; Redis progress counters per assignment; `GET /assignments/{id}/grading-status` reads from Redis; assignment status transitions; per-essay retry endpoint `POST /essays/{id}/grade/retry`
- **Batch grading UI** — "Grade now" trigger button; real-time progress bar (polls every 3 s, stops on completion); per-essay status list; failed essay display with retry action; in-app toast on completion
- **Feedback generation** — grading prompt extended to return per-criterion feedback note and overall summary feedback paragraph; tone parameter (encouraging / direct / academic) configurable per assignment; feedback stored on `CriterionScore.feedback` and `Grade.summary_feedback`
- **Comment bank API** — `GET/POST /comment-bank`, `DELETE /comment-bank/{id}`; save any feedback snippet; fuzzy-match suggestion endpoint for similar issues; scoped to teacher
- **Grade read and edit API** — `GET /essays/{id}/grade` (full grade with all criterion scores and feedback); `PATCH /grades/{id}/feedback` (summary feedback override); `PATCH /grades/{id}/criteria/{criterionId}` (per-criterion score and feedback override); `POST /grades/{id}/lock` (finalize grade); all writes are INSERT-only audit log entries (`before_value` / `after_value`); locked grades reject further edits with 409
- **Essay review interface** — two-panel layout (essay text left, rubric scores + AI justifications + feedback right); inline score override with live weighted total recalculation; inline feedback text editor; lock grade button; keyboard-navigable
- **Review queue** — list view of all essays in an assignment with status badges (unreviewed / in-review / locked); sort by status, score, student name; filter controls; keyboard navigation; link-through to individual essay review
- **Audit log read API** — `GET /grades/{id}/audit` returns full change history for a grade with timestamps, actor, action type, and before/after values
- **Export API and Celery task** — `POST /assignments/{id}/export` enqueues async export task; task generates per-student feedback PDFs, packages as ZIP, uploads to S3; `GET /exports/{taskId}/status` polls progress; `GET /exports/{taskId}/download` returns pre-signed S3 URL
- **CSV grade export** — `GET /assignments/{id}/grades.csv` synchronous export of all locked grades (student name, per-criterion scores, weighted total); compatible with LMS gradebook import formats
- **Export UI** — Export button on assignment view; options picker (PDF batch ZIP, CSV grades, copy individual student feedback to clipboard); async ZIP download flow with progress indicator

### Security
- **Prompt injection defense** — essay content strictly in LLM `user` role; system prompt contains explicit directive to ignore instructions in essay text; essay delimited with `<ESSAY_START>` / `<ESSAY_END>` markers; LLM response validated against schema before any DB write
- **Score clamping** — criterion scores returned by LLM clamped server-side to `[criterion.min_score, criterion.max_score]`; out-of-range values logged as `score_clamped` audit events before clamp
- **File upload safety** — MIME type validated server-side with `python-magic` (not file extension); only `application/pdf`, `application/vnd.openxmlformats-officedocument.wordprocessingml.document`, `text/plain` accepted; size limit enforced before reading content; files stored to S3 before extraction
- **Audit log is INSERT-only** — no UPDATE or DELETE paths on `audit_logs`; every grade mutation writes a log entry with actor, timestamp, before/after values
- **No student PII in logs** — `logger.*` calls use entity IDs only (`essay_id`, `student_id`, `grade_id`); no names, essay text, scores, or feedback in any log line
- **Rubric snapshot immutability** — grading code reads `assignment.rubric_snapshot` exclusively; editing the live rubric never affects grades already in progress

### Fixed
- mypy and ruff errors surfaced after M3.14–M3.20 integration (PR #100): type annotations, import ordering, unused imports

### Tests added
- Backend unit tests covering rubric service weight validation, rubric snapshot write, student fuzzy-matching logic, LLM response validation, score clamping, grade lock idempotency, and audit log INSERT enforcement
- Frontend Vitest tests for rubric builder UI, assignment creation form, essay upload flow, auto-assignment review screen, batch grading panel, essay review panel, review queue, and export panel

---

## [v0.3.0] — M2 Public Website & Onboarding — Unreleased (pending merge to main)

### Added
- **Public site layout** — `/(public)/` route group with shared header (Product, How It Works, Pricing, AI, About, Sign In, Start Trial CTA) and footer; `PRODUCT_NAME` constant; middleware redirects authenticated users from `/login` and `/signup` to `/dashboard`
- **Landing page (`/`)** — hero, problem/solution, feature highlight cards, how-it-works steps, and CTA section; fully static
- **Product & How It Works pages** — `/product` feature deep-dive with screenshot placeholders and trust callout; `/how-it-works` numbered workflow timeline
- **About page (`/about`)** — mission statement, core principles, team placeholder, contact callout
- **Pricing page (`/pricing`)** — tier cards (Trial/Teacher/School/District), annual/monthly toggle, feature comparison table, FAQ accordion; school inquiry form posts to `POST /api/v1/contact/inquiry`
- **AI transparency page (`/ai`)** — 5-step grading explanation, HITL guarantee callout, data use disclosure, confidence score explainer
- **Legal pages (`/legal/*`)** — Terms of Service, Privacy Policy, FERPA/COPPA Notice, DPA info page (with DPA request form → `POST /api/v1/contact/dpa-request`), AI Use Policy; `[ATTORNEY DRAFT REQUIRED]` banner on all pages
- **Sign-up flow** — `POST /api/v1/auth/signup` (bcrypt, email verification Celery task, 201); `GET /api/v1/auth/verify-email` (HMAC-signed token, Redis TTL); `POST /api/v1/auth/resend-verification`; `/signup`, `/signup/verify`, `/auth/verify` pages; rate-limited to 5 attempts/IP/hour
- **Onboarding wizard** — `/(onboarding)/` route group; 2-step wizard (create class → build rubric or skip); `GET /api/v1/onboarding/status`; `POST /api/v1/onboarding/complete`; `/onboarding/done` completion page; trial status banner in dashboard layout
- **Trial lifecycle emails** — Celery tasks for welcome, 7-day warning, 1-day warning, and day-0 expiry emails; Celery Beat schedule for daily scan; plain HTML via SMTP; unsubscribe link on non-transactional emails; `GET /api/v1/account/trial` endpoint
- **Contact & DPA backend** — `POST /api/v1/contact/inquiry` and `POST /api/v1/contact/dpa-request` with Redis rate limiting, Pydantic validation, audit log entries, and Celery notification email tasks
- **`email-validator` dependency** — added to `pyproject.toml` for `EmailStr` Pydantic field validation

### Security
- All public form endpoints (`/contact/inquiry`, `/contact/dpa-request`, `/auth/signup`) rate-limited per IP via Redis counters
- Email verification token is HMAC-signed, single-use, 24-hour TTL stored in Redis
- Password hashed with bcrypt; minimum 8 characters enforced by Pydantic and Zod
- No student PII collected or stored in any M2 endpoint — all data is teacher/admin only
- `INTEGRITY_SIMILARITY_THRESHOLD` false positive added to gitleaks allowlist

### Fixed
- Removed conflicting `(public)/signup/page.tsx` stub — real sign-up page lives in `(auth)/signup`
- Added `from __future__ import annotations` to `routers/contact.py`, `services/contact.py`, `services/dpa.py` to resolve `Redis[Any]` FastAPI annotation evaluation error; function signatures use plain `Redis` with `# type: ignore[type-arg]`

### Tests added
- `backend/tests/unit/` — `test_auth_router.py`, `test_auth_router_login.py`, `test_account_router.py`, `test_contact_router.py`, `test_dpa_router.py`, `test_onboarding_router.py` (245 unit tests total)
- `frontend/tests/` — signup form, onboarding wizard, legal DPA form, pricing inquiry form, middleware redirect tests (198 Vitest tests total)
- **Playwright E2E infrastructure** — `frontend/playwright.config.ts`; `tests/e2e/` spec suite covering public-site routes, auth flows, onboarding, and M3 journey stubs; `helpers.ts` with `assertBasicA11y`, `waitForEmail`, `extractLinkFromEmail`, `clearMailpit` utilities; Vitest configured to exclude `tests/e2e/**`
- **E2E CI job** — `E2E Tests (Playwright)` job in `ci.yml`; spins up full Docker Compose stack, runs `alembic upgrade head` via one-shot container, polls all services with `scripts/smoke_test.py` before Playwright runs; uploads test reports as artifacts on failure
- **`.env.ci`** — committed environment template with safe placeholder secrets used by the CI E2E job; `.gitignore` exception added

### Infrastructure added
- **`scripts/smoke_test.py`** — 17-check readiness script (backend health, all public frontend routes, Mailpit web UI + API); retries with configurable delay; used as a CI gate before Playwright
- **`docker-compose.yml`** — added Mailpit service (SMTP sink + web UI) for local dev and CI email testing
- **`docker-compose.demo.yml`** — self-contained demo stack; all env vars inlined (no `.env` needed); `demo-seed` one-shot service runs migrations automatically on first start; uses separate `demo_*` volumes (never touches dev data); OpenAI key optional
- **`scripts/smoke_test_demo.py`** — 18-check demo smoke test with built-in readiness wait loop (`--max-wait`, `--no-wait`, `--retries` flags); stdlib only, no pip install required; prints direct service URLs on success
- **`DEMO.md`** — step-by-step local demo guide: 3-command quick start, service URL table, sign-up walkthrough, OpenAI key instructions, troubleshooting section, stop/reset/rebuild reference, dev-vs-demo comparison table; linked from `README.md`

---

## [v0.2.0] — M1 Project Scaffold — Unreleased (pending merge to main)

### Added
- **FastAPI backend bootstrap** — app factory pattern, `GET /api/v1/health` endpoint, structured JSON error responses for all unhandled exceptions (`app/main.py`, `app/exceptions.py`, `app/routers/health.py`)
- **pydantic-settings configuration layer** — `app/config.py` loads all environment variables with typed defaults; secrets accessed only via `settings.*`, never `os.environ` directly
- **Async SQLAlchemy session factory** — `app/db/session.py` using `asyncpg` driver; `AsyncSession` available for all database operations
- **Alembic migration scaffold** — `alembic.ini`, `app/db/migrations/env.py` with async migration support and `autocommit_block()` for `CREATE INDEX CONCURRENTLY`
- **Celery worker + Redis broker** — `app/tasks/celery_app.py`; smoke-test `ping` task in `app/tasks/debug.py`; all broker/result config from `settings`
- **S3/MinIO client wrapper** — `app/storage/s3.py` with `upload_file()` and `generate_presigned_url()`; configurable endpoint for both AWS S3 and MinIO; no credentials hardcoded
- **Next.js 15 frontend bootstrap** — TypeScript, App Router, Tailwind CSS, shadcn/ui, TanStack Query v5, React Hook Form, Zod; `/(auth)/` and `/(dashboard)/` route groups
- **Typed API client** — `frontend/lib/api/client.ts` and `lib/api/baseFetch.ts`; all API calls go through this layer; silent JWT refresh on 401; no raw `fetch` in components
- **Frontend auth** — Login page (`/login`), `middleware.ts` protecting `/(dashboard)/*`, in-memory token storage, `lib/auth/session.ts`, `lib/utils/redirect.ts` with open-redirect guard
- **Backend + frontend Dockerfiles** — production-ready multi-stage builds for both services

### Security
- Next.js upgraded 14.2.35 → 15.5.15 to patch two DoS CVEs flagged by `npm audit`
- S3 object keys never appear in logs or error messages (FERPA compliance)
- Access tokens stored in memory only — never in `localStorage`, `sessionStorage`, or cookies
- Open-redirect guard on all post-login redirect destinations
- All secrets read from `settings.*`; `os.environ` access blocked by convention

### Tests added
- `backend/tests/unit/` — `test_config.py`, `test_main.py`, `test_session.py`, `test_celery_app.py`, `test_s3.py`
- `backend/tests/integration/test_s3.py` — MinIO testcontainer integration test
- `frontend/tests/unit/` — `api-client.test.ts`, `session.test.ts`, `redirect.test.ts`

---

<!-- Milestone releases are prepended here automatically by the release workflow -->
