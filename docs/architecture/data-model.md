# Data Model

## Overview

This document defines the core entities, their relationships, and key field-level decisions. All entities are stored in PostgreSQL. The model is designed to support longitudinal student tracking across classes and academic years while keeping the grading pipeline efficient.

---

## Entity Relationship Summary

```
User (Teacher)
  └── Class (many, scoped to academic_year)
        ├── ClassEnrollment → Student (many-to-many)
        └── Assignment
              ├── Rubric (one, snapshot at time of assignment)
              └── Essay
                    ├── EssayVersion (many — supports resubmission)
                    │     └── Grade
                    │           └── CriterionScore (one per rubric criterion)
                    └── IntegrityReport

Student (persistent across classes and years)
  └── StudentSkillProfile (one per student — aggregated, updated on each grade)

Rubric (owned by teacher, reusable)
  └── RubricCriterion (many)

AuditLog (append-only, references any entity)
```

---

## Entities

### User
Represents a teacher account.

| Column | Type | Notes |
|---|---|---|
| id | UUID | Primary key |
| email | VARCHAR(255) | Unique, used for login |
| hashed_password | TEXT | bcrypt |
| full_name | VARCHAR(255) | |
| role | ENUM | `teacher`, `admin` |
| created_at | TIMESTAMPTZ | |
| last_login_at | TIMESTAMPTZ | Nullable |
| onboarding_complete | BOOLEAN | `false` until wizard completed; set via `POST /onboarding/complete` |
| trial_ends_at | TIMESTAMPTZ | Nullable; set to `verification time + 30 days` on email verification |

---

### Class
A teacher's class, scoped to an academic year.

| Column | Type | Notes |
|---|---|---|
| id | UUID | Primary key |
| teacher_id | UUID | FK → User |
| name | VARCHAR(255) | e.g., "Period 2 English" |
| subject | VARCHAR(100) | e.g., "English Language Arts" |
| grade_level | VARCHAR(20) | e.g., "9th Grade" |
| academic_year | VARCHAR(10) | e.g., "2025-26" |
| is_archived | BOOLEAN | Default false |
| created_at | TIMESTAMPTZ | |

**Index:** `(teacher_id, academic_year, is_archived)`

---

### Student
A persistent student record, independent of any class. Identity survives class transfers and year transitions.

| Column | Type | Notes |
|---|---|---|
| id | UUID | Primary key |
| teacher_id | UUID | FK → User (owning teacher) |
| full_name | VARCHAR(255) | |
| external_id | VARCHAR(255) | Nullable — LMS student ID for sync |
| created_at | TIMESTAMPTZ | |

**Note:** Students are owned by a teacher at creation. Cross-teacher sharing is deferred (see Open Questions in class-roster-student-management.md).

---

### ClassEnrollment
Join table linking students to classes. Tracks enrollment history.

| Column | Type | Notes |
|---|---|---|
| id | UUID | Primary key |
| class_id | UUID | FK → Class |
| student_id | UUID | FK → Student |
| enrolled_at | TIMESTAMPTZ | |
| removed_at | TIMESTAMPTZ | Nullable — soft removal |

**Unique constraint:** `(class_id, student_id)` where `removed_at IS NULL`

---

### Rubric
A reusable grading rubric owned by a teacher.

| Column | Type | Notes |
|---|---|---|
| id | UUID | Primary key |
| teacher_id | UUID | FK → User |
| name | VARCHAR(255) | |
| description | TEXT | Nullable |
| is_template | BOOLEAN | Teacher-saved templates |
| created_at | TIMESTAMPTZ | |
| updated_at | TIMESTAMPTZ | |

---

### RubricCriterion
A single criterion within a rubric.

| Column | Type | Notes |
|---|---|---|
| id | UUID | Primary key |
| rubric_id | UUID | FK → Rubric |
| name | VARCHAR(255) | e.g., "Thesis Statement" |
| description | TEXT | What this criterion assesses |
| weight | DECIMAL(5,2) | Percentage weight (all criteria must sum to 100) |
| min_score | INTEGER | e.g., 1 |
| max_score | INTEGER | e.g., 5 |
| display_order | INTEGER | Ordering within the rubric |
| anchor_descriptions | JSONB | Nullable — score-level exemplars `{1: "...", 5: "..."}` |

---

### Assignment
An assignment within a class, linking a rubric to a set of essays.

| Column | Type | Notes |
|---|---|---|
| id | UUID | Primary key |
| class_id | UUID | FK → Class |
| rubric_id | UUID | FK → Rubric |
| rubric_snapshot | JSONB | Full rubric copy at time of assignment creation — protects against rubric edits mid-assignment |
| title | VARCHAR(255) | |
| prompt | TEXT | Nullable — assignment instructions |
| due_date | DATE | Nullable |
| status | ENUM | `draft`, `open`, `grading`, `review`, `complete`, `returned` |
| resubmission_enabled | BOOLEAN | Default false |
| resubmission_limit | INTEGER | Nullable — max resubmissions per student |
| created_at | TIMESTAMPTZ | |

---

### Essay
A student's submission for an assignment. One essay per student per assignment; versions tracked separately.

| Column | Type | Notes |
|---|---|---|
| id | UUID | Primary key |
| assignment_id | UUID | FK → Assignment |
| student_id | UUID | FK → Student — nullable until assigned |
| status | ENUM | `unassigned`, `queued`, `grading`, `graded`, `reviewed`, `locked`, `returned` |
| submitted_at | TIMESTAMPTZ | |
| created_at | TIMESTAMPTZ | |

---

### EssayVersion
A specific version of an essay (original submission or resubmission).

| Column | Type | Notes |
|---|---|---|
| id | UUID | Primary key |
| essay_id | UUID | FK → Essay |
| version_number | INTEGER | 1 = original, 2+ = resubmissions |
| content | TEXT | Full essay text |
| file_storage_key | VARCHAR(500) | Nullable — S3 key for original uploaded file |
| word_count | INTEGER | |
| submitted_at | TIMESTAMPTZ | |

---

### Grade
The grading result for a specific essay version. One grade per essay version.

| Column | Type | Notes |
|---|---|---|
| id | UUID | Primary key |
| essay_version_id | UUID | FK → EssayVersion |
| total_score | DECIMAL(6,2) | Weighted total |
| max_possible_score | DECIMAL(6,2) | |
| summary_feedback | TEXT | Overall AI-generated feedback |
| summary_feedback_edited | TEXT | Nullable — teacher-edited version |
| strictness | ENUM | `lenient`, `balanced`, `strict` |
| ai_model | VARCHAR(100) | Model used to generate this grade |
| is_locked | BOOLEAN | Default false |
| locked_at | TIMESTAMPTZ | Nullable |
| created_at | TIMESTAMPTZ | |

---

### CriterionScore
Per-criterion score within a grade.

| Column | Type | Notes |
|---|---|---|
| id | UUID | Primary key |
| grade_id | UUID | FK → Grade |
| rubric_criterion_id | UUID | FK → RubricCriterion |
| ai_score | INTEGER | Score as returned by the LLM |
| teacher_score | INTEGER | Nullable — set only if teacher overrides |
| final_score | INTEGER | Computed: `teacher_score ?? ai_score` |
| ai_justification | TEXT | AI reasoning for the score |
| teacher_feedback | TEXT | Nullable — teacher-written criterion feedback |
| confidence | ENUM | `high`, `medium`, `low` |
| created_at | TIMESTAMPTZ | |

---

### IntegrityReport
Academic integrity signals for an essay version.

| Column | Type | Notes |
|---|---|---|
| id | UUID | Primary key |
| essay_version_id | UUID | FK → EssayVersion |
| ai_likelihood | ENUM | `low`, `moderate`, `high` |
| ai_likelihood_score | DECIMAL(5,4) | Raw score 0.0–1.0 |
| similarity_score | DECIMAL(5,4) | Overall similarity percentage |
| flagged_passages | JSONB | Array of `{text, start_char, end_char, signal_type, source}` |
| review_status | ENUM | `pending`, `reviewed_clear`, `flagged` |
| reviewed_at | TIMESTAMPTZ | Nullable |
| created_at | TIMESTAMPTZ | |

---

### StudentSkillProfile
Aggregated skill profile for a student, updated incrementally after each graded assignment. Stored as a single row per student for fast reads.

| Column | Type | Notes |
|---|---|---|
| id | UUID | Primary key |
| student_id | UUID | FK → Student, unique |
| skill_scores | JSONB | `{skill_name: {avg_score, trend, data_points, last_updated}}` |
| last_updated_at | TIMESTAMPTZ | |
| assignment_count | INTEGER | Number of graded assignments contributing to this profile |

**Note:** `skill_scores` uses normalized skill dimension names (e.g., "thesis", "evidence", "organization") mapped from rubric criterion names at grade time. Mapping logic is documented in the data-ingestion guide.

---

### AuditLog
Append-only record of every consequential action. Never updated or deleted.

| Column | Type | Notes |
|---|---|---|
| id | UUID | Primary key |
| teacher_id | UUID | FK → User — nullable for system-generated events |
| entity_type | VARCHAR(50) | e.g., `grade`, `criterion_score`, `essay`, `auth`, `export` |
| entity_id | UUID | Nullable — ID of the affected entity (null for auth events) |
| action | VARCHAR(100) | See action catalog below |
| before_value | JSONB | Nullable — state before the change |
| after_value | JSONB | Nullable — state after the change |
| ip_address | INET | Nullable — client IP for auth and access events |
| metadata | TEXT | Nullable — free-form extra context that doesn't fit `before_value`/`after_value` (e.g. user-agent string) |
| created_at | TIMESTAMPTZ | |

**Index:** `(entity_type, entity_id)`, `(teacher_id, created_at DESC)`, `(action, created_at DESC)`

**Action catalog** (required for SOC 2 CC6 and PI1 — see `docs/architecture/security.md#6-soc-2-readiness`):

| Category | `action` value | `entity_type` | Notes |
|---|---|---|---|
| Auth | `login_success` | `auth` | `after_value`: `{teacher_id}` |
| Auth | `login_failure` | `auth` | `after_value`: `{email_attempted}` — no PII beyond the attempt |
| Auth | `logout` | `auth` | |
| Auth | `token_refreshed` | `auth` | |
| Auth | `password_reset_requested` | `auth` | |
| Auth | `password_reset_completed` | `auth` | |
| Grade | `score_override` | `criterion_score` | `before_value`/`after_value`: `{score, feedback}` |
| Grade | `feedback_edited` | `grade` | `before_value`/`after_value`: `{summary_feedback}` |
| Grade | `grade_locked` | `grade` | |
| Grade | `score_clamped` | `criterion_score` | `before_value`: LLM raw score; `after_value`: clamped score |
| Grade | `regrade_resolved` | `grade` | |
| Data access | `export_requested` | `export` | `after_value`: `{assignment_id, format}` |
| Data access | `export_downloaded` | `export` | |
| Data lifecycle | `student_data_deletion_requested` | `student` | FERPA deletion request |
| Data lifecycle | `student_data_deletion_completed` | `student` | Background job completion |
| Data lifecycle | `class_archived` | `class` | |
| Admin | `teacher_account_created` | `user` | |
| Admin | `teacher_account_deactivated` | `user` | |

---

## Key Design Decisions

### Rubric snapshots on assignments
When a teacher creates an assignment, the current rubric is snapshotted into `rubric_snapshot` (JSONB). This means rubric edits after assignment creation do not affect existing grades. The live `Rubric` record can evolve; the assignment always grades against the version that was active at creation time.

### `final_score` as a computed field
`CriterionScore.final_score` is always `teacher_score ?? ai_score`. This makes queries simple — always read `final_score` for display and calculations. The original AI score is never lost.

### Student identity is teacher-scoped at MVP
Students are created by and belong to a teacher. Cross-teacher student sharing (e.g., a student appearing in two teachers' classes) is deferred. When implemented, it will require a resolution model for conflicting profile data.

### Skill normalization in StudentSkillProfile
Rubric criteria names vary across assignments ("Main Argument" vs "Thesis Statement"). A normalization layer maps raw criterion names to canonical skill dimensions at grade-write time. The mapping is configurable and documented in the data-ingestion guide.

---

## Open Questions

- Should `StudentSkillProfile` be a materialized view computed from `CriterionScore` records, or a maintained JSONB column? Materialized view is more correct; maintained column is faster for reads.
- How do we handle skill normalization for rubrics in subjects beyond English writing (Phase expansion)?
- Should `AuditLog` have its own schema or database to prevent it from affecting main DB performance at scale?
