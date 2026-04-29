# M5 Student Intelligence — Technical Release Notes

**Release**: v0.6.0  
**Milestone**: M5 — Student Intelligence  
**Date**: April 2026  
**PRs**: #168–#179 (12 pull requests)  
**Branch**: `release/m5` → `main`

---

## Database Migrations (Alembic)

All migrations are reversible. Run order is enforced by the revision chain.

| # | Migration | Key change |
|---|---|---|
| 022 | `student_skill_profiles_create_table` | New `student_skill_profiles` table: `student_id` (FK → `students`), `teacher_id` (FK → `users`), `skill_scores JSONB`, `last_updated_at TIMESTAMPTZ` — unique on `(student_id, teacher_id)` |
| 023 | `essay_add_browser_written_flag` | `browser_written BOOLEAN NOT NULL DEFAULT false` on `essays` |
| 024 | `essay_versions_add_snapshot_metadata` | `snapshot_type VARCHAR(20)` (`auto`/`manual`/`final`) and `word_count INT` on `essay_versions` |

---

## New API Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/v1/students/{id}` | Student detail with embedded `skill_profile` (scores, trends, data point counts per dimension) |
| `GET` | `/api/v1/students/{id}/history` | All graded assignments for student in chronological order with per-criterion scores |
| `GET` | `/api/v1/classes/{id}/insights` | Class-level skill averages, score distributions, common feedback issues |
| `GET` | `/api/v1/assignments/{id}/analytics` | Per-assignment skill breakdown and score distributions |
| `GET` | `/api/v1/essays/{id}/snapshots` | Essay snapshot history for writing process timeline |
| `POST` | `/api/v1/essays/{id}/snapshots` | Save incremental essay snapshot (debounced from browser) |

### Updated endpoints
- `GET /api/v1/students/{id}` — now includes `skill_profile` and `teacher_notes` fields
- `PATCH /api/v1/students/{id}` — accepts `teacher_notes` update

---

## New Backend Modules

| Path | Purpose |
|---|---|
| `app/models/student_skill_profile.py` | `StudentSkillProfile` SQLAlchemy model |
| `app/services/skill_normalization.py` | Fuzzy criterion-name → canonical skill dimension mapping (config-driven, `rapidfuzz`) |
| `app/services/student_skill_profile.py` | Weighted-average aggregation, trend detection, upsert logic |
| `app/services/class_insights.py` | Class-level skill aggregation and common-issues analysis |
| `app/services/composition_timeline.py` | Snapshot parsing: session detection, paste-event detection, active-writing-time computation |
| `app/tasks/skill_profile.py` | `update_skill_profile` Celery task (triggered on grade lock) |
| `app/routers/students.py` | Extended student router (profile + history endpoints) |
| `app/routers/classes.py` | Extended class router (`/insights` endpoint) |

### New config file
- `app/skill_normalization_config.json` — canonical dimension mapping; overridable via `SKILL_NORMALIZATION_CONFIG_PATH` env var

---

## New Environment Variables

| Variable | Default | Description |
|---|---|---|
| `SKILL_NORMALIZATION_CONFIG_PATH` | _(bundled config)_ | Path to a custom skill-normalization JSON mapping. Omit to use the built-in English writing config. |

---

## New Frontend Components

| Component | Path | Description |
|---|---|---|
| `StudentProfilePage` | `app/(dashboard)/dashboard/classes/[classId]/students/[studentId]/page.tsx` | Full student detail: skill bar chart, assignment history timeline, strengths/gaps callouts, growth indicators, private notes |
| `SkillHeatmapPanel` | `components/insights/SkillHeatmapPanel.tsx` | Class heatmap grid (students × skills), color-coded by score, sortable, links to student profiles |
| `ClassInsightsPanel` | `components/insights/ClassInsightsPanel.tsx` | Common-issues list, score distribution histogram, cross-assignment trend chart |
| `WritingProcessPanel` | `components/essays/WritingProcessPanel.tsx` | Session timeline, paste-event flags, snapshot viewer (view essay at any saved point), process insight callout |
| `BrowserWritingInterface` | `components/essays/BrowserWritingInterface.tsx` | Rich-text writing area with debounced autosave (10 s), word count, cancel/submit, paste sanitization |

---

## Celery Tasks

| Task | Trigger | Description |
|---|---|---|
| `update_skill_profile` | Grade lock (`POST /grades/{id}/lock`) | Loads all locked criterion scores for student → normalizes to skill dimensions → computes weighted average with recency weighting → detects trend direction → upserts `StudentSkillProfile` |

---

## Skill Normalization Design

Criterion names entered by teachers (free-form rubric fields) are mapped to seven canonical skill dimensions at grade-lock time:

| Dimension | Examples of matched criterion names |
|---|---|
| `thesis` | Thesis Statement, Claim, Central Argument, Controlling Idea |
| `evidence` | Evidence Use, Supporting Details, Citations, Use of Sources |
| `organization` | Organization, Structure, Paragraph Flow, Logical Order |
| `analysis` | Analysis, Critical Thinking, Depth of Reasoning, Interpretation |
| `mechanics` | Grammar, Mechanics, Conventions, Spelling and Punctuation |
| `voice` | Voice, Tone, Style, Word Choice, Author's Voice |
| `other` | Any criterion that does not fuzzy-match any of the above |

- Matching uses `rapidfuzz` token-set ratio with a configurable threshold (default: 80).
- The mapping config (`skill_normalization_config.json`) can be swapped without code changes — supports non-English subjects and custom rubric vocabularies.
- Criterion names are never emitted in log messages (treated as potentially containing student PII).

---

## Weighted Average Algorithm

Skill scores are computed per student per dimension:

1. Collect all locked `CriterionScore` rows for the student, sorted by `Grade.locked_at` ascending.
2. Assign a recency weight to each assignment: assignment at index `i` (0-based, oldest first) gets weight `i + 1`.
3. Normalize each raw score to `[0.0, 1.0]` using `(score - min_score) / (max_score - min_score)`, clamped.
4. Compute weighted average: `Σ(weight × normalized_score) / Σ(weight)`.
5. Trend is `improving` if the two most recent scores are strictly ascending, `declining` if descending, else `stable`.
6. Store `final_score`, `trend`, and `data_point_count` in `skill_scores JSONB` per dimension.

---

## Security Notes

- `StudentSkillProfile` is tenant-scoped: all queries include `teacher_id` in the WHERE clause — no cross-teacher access possible.
- Essay snapshot content is not logged; only `essay_id` and operation type appear in log lines.
- `teacher_notes` on `Student` is stored in the `students` table (teacher-scoped) and is never surfaced to any student-facing path.
- The browser writing interface sanitizes pasted HTML (strips `<script>`, event handlers, tracking pixels) before saving snapshots.

---

## Tests Added

### Backend
- `tests/unit/test_skill_normalization.py` — mapping load, fuzzy match, unmapped → `other`, custom config path
- `tests/unit/test_student_skill_profile.py` — weighted average, trend detection, score clamping, upsert idempotency
- `tests/unit/test_skill_profile_task.py` — Celery task: single/multi-assignment aggregation, trend over three assignments, lock trigger
- `tests/unit/test_class_insights_service.py` — class average, distribution, common-issues ranking
- `tests/unit/test_composition_timeline.py` — session detection, paste-event detection, active-writing-time computation, rapid-completion flag
- `tests/unit/test_student_service.py` — profile embed, history sort, teacher-notes PATCH
- `tests/unit/test_browser_compose.py` — snapshot save, snapshot fetch, word count

### Frontend
- `tests/unit/student-profile.test.tsx` — skill bar chart render, assignment history, notes save/error/pending
- `tests/unit/skill-heatmap.test.tsx` — grid render, sort by skill, link-through to student profile
- `tests/unit/class-insights-panel.test.tsx` — common issues, distribution histogram, trend chart
- `tests/unit/writing-process-panel.test.tsx` — timeline render, snapshot viewer, paste-event flag, process callout
- `tests/unit/browser-writing-interface.test.tsx` — autosave debounce, save-failed status, paste sanitization, submit/cancel

### E2E
- `tests/e2e/student-profile.spec.ts` — Journey 5: teacher locks grades across two assignments → student profile shows skill scores → skill history chart shows trend → strengths/gaps callouts match data

---

## Upgrade Notes

No breaking API changes. Existing grades, essays, and rubrics are unaffected.

**New migration required**: run `alembic upgrade head` after deploying the M5 backend image. The three migrations are additive (new table, new columns with defaults) — no data backfill required and no downtime risk.

**Skill profiles are populated lazily**: profiles are created only when a grade is locked after the M5 deploy. Existing locked grades from M1–M4 do not automatically generate profiles. A one-time backfill task can be run manually if historical profile data is needed (`python scripts/backfill_skill_profiles.py` — not shipped in M5, planned for M6).
