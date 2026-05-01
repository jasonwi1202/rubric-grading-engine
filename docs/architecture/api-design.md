# API Design

## Overview

The backend exposes a REST API consumed exclusively by the Next.js frontend. All endpoints are versioned under `/api/v1`. The API is not a public API — it is an internal interface between the frontend and backend. Design decisions prioritize clarity and consistency over flexibility.

---

## Conventions

### URL Structure
- Resources are plural nouns: `/classes`, `/essays`, `/rubrics`
- Nested resources reflect ownership: `/classes/{classId}/assignments`
- Actions that are not CRUD use POST with a descriptive path segment: `/grades/{id}/lock`, `/assignments/{id}/grade`

### HTTP Methods
| Method | Use |
|---|---|
| GET | Read — never mutates state |
| POST | Create a new resource, or trigger an action |
| PATCH | Partial update — only send changed fields |
| DELETE | Soft delete only — no hard deletes in the application layer |

### Response Format
All responses follow a consistent envelope:
```json
{
  "data": { ... },
  "meta": { "page": 1, "total": 42 }   // present on list endpoints only
}
```

**Exception — file download endpoints:** Endpoints that stream binary or text files (e.g., `GET /assignments/{assignmentId}/grades.csv`) return the file content directly with the appropriate `Content-Type` (e.g., `text/csv`) and `Content-Disposition: attachment` header.  These endpoints do **not** use the `{"data": ...}` envelope and cannot be called via the shared `apiGet()` helper.  See the individual endpoint documentation for frontend integration guidance.

Errors:
```json
{
  "error": {
    "code": "RUBRIC_NOT_FOUND",
    "message": "Rubric with id abc123 does not exist.",
    "field": "rubric_id"   // present on validation errors only
  }
}
```

### Pagination
All list endpoints accept `?page=1&page_size=25`. Default page size: 25. Max: 100.

### Authentication
All endpoints require a valid JWT Bearer token in the `Authorization` header unless explicitly documented as public. Unauthenticated requests return `401`. Requests for resources the authenticated teacher does not own return `403` (not `404` — do not leak existence).

**Exception — FORCE RLS anti-enumeration endpoints:** Endpoints whose service layer uses a single `WHERE id = ? AND teacher_id = ?` query (matching the worklist `_load_worklist_item` pattern) cannot distinguish a cross-tenant ID from a nonexistent ID at the DB level, because FORCE RLS filters the row out before the application sees it. These endpoints return `404` for both missing and cross-tenant IDs. The endpoint description will explicitly note this behavior. Example: `POST /recommendations/{recommendationId}/assign`.

**Public endpoints (no JWT required):**
- `POST /auth/signup` — create a new teacher account
- `GET /auth/verify-email` — verify email address via HMAC token
- `POST /auth/resend-verification` — resend the verification email
- `POST /contact/inquiry` — unauthenticated school/district inquiry form submission
- `POST /contact/dpa-request` — unauthenticated DPA request from a school/district administrator

---

## Endpoint Reference

### Auth

| Method | Path | Description |
|---|---|---|
| POST | `/auth/signup` | Create a new teacher account (public) |
| GET | `/auth/verify-email` | Verify email via HMAC token (public) |
| POST | `/auth/resend-verification` | Resend verification email (public) |
| POST | `/auth/login` | Issue access + refresh tokens |
| POST | `/auth/refresh` | Exchange refresh token for new access token |
| POST | `/auth/logout` | Invalidate refresh token |

**POST /auth/signup body:**
```json
{
  "email": "teacher@school.edu",
  "password": "SecurePass1",
  "first_name": "Alex",
  "last_name": "Smith",
  "school_name": "Lincoln High School"
}
```
Returns `201` with `{"data": {"id": "<uuid>", "email": "...", "created_at": "...", "message": "..."}}`.  
Returns `409` if the email is already registered.  
Returns `429` if more than 5 sign-up attempts are made from the same IP in one hour.

**GET /auth/verify-email query params:** `?token=<raw_token>`  
Consumes a single-use token (24 h TTL). The server computes an HMAC-SHA256 tag over the raw token to look up the Redis entry — the token itself is a random URL-safe string, not an encoded signature. Returns `200` on success, `422` for invalid/expired/already-used token.

**POST /auth/resend-verification body:**
```json
{ "email": "teacher@school.edu" }
```
Always returns `202` regardless of whether the email is registered (avoids account-existence oracle).  
Returns `429` if more than 3 resend requests are made for the same email in one hour.

**POST /auth/login body:**
```json
{ "email": "teacher@school.edu", "password": "SecurePass1" }
```
Returns `200` with `{"data": {"access_token": "<jwt>", "token_type": "bearer"}}`.  
Sets an `httpOnly; SameSite=Strict` cookie named `refresh_token` (7-day TTL). The cookie includes `Secure` in staging/production over HTTPS; `Secure` is disabled in local development for `http://localhost`.  
Returns `422` for invalid credentials or unverified email.

**POST /auth/refresh** (no body; reads `refresh_token` cookie)  
Returns `200` with a new `{"data": {"access_token": "<jwt>", "token_type": "bearer"}}`.  
Rotates the refresh token (old token invalidated, new cookie set with the same environment-dependent attributes: `Secure` in staging/production, disabled for local development).  
Returns `401` if the cookie is absent; `422` if the token is invalid or expired.

**POST /auth/logout** (no body; reads `refresh_token` cookie)  
Returns `204`. Invalidates the refresh token server-side and clears the cookie using the same environment-appropriate cookie attributes.  
Idempotent — always returns `204` regardless of whether the cookie was present.

---

### Onboarding

| Method | Path | Description |
|---|---|---|
| GET | `/onboarding/status` | Return the teacher's current wizard step and completion flag |
| POST | `/onboarding/complete` | Mark the teacher's onboarding as complete |

**GET /onboarding/status** (requires JWT)
```json
{
  "data": {
    "step": 1,
    "completed": false,
    "trial_ends_at": "2026-05-17T00:00:00Z"
  }
}
```
`step` is `1` when `onboarding_complete = false` (defaults until M3 class/rubric tables allow more granular checks). `step` is `2` when `onboarding_complete = true`.  
`trial_ends_at` is `null` until email verification sets it to `now + 30 days`.

**POST /onboarding/complete** (requires JWT)  
Idempotent — safe to call multiple times.  
Returns `200` with `{"data": {"message": "Onboarding marked as complete."}}`.

---

### Account

| Method | Path | Description |
|---|---|---|
| GET | `/account/trial` | Return the authenticated teacher's trial status |

**GET /account/trial** (requires JWT)
```json
{
  "data": {
    "trial_ends_at": "2026-05-17T00:00:00Z",
    "is_active": true,
    "days_remaining": 29
  }
}
```
- `trial_ends_at`: ISO-8601 timestamp when the trial ends, or `null` if not yet set (email not yet verified).
- `is_active`: `true` while `trial_ends_at` is in the future or not set; `false` once the trial has expired.
- `days_remaining`: number of full 24-hour periods remaining (`Math.floor`); `null` if `trial_ends_at` is not set. This value may be `0` while `is_active` is still `true` when fewer than 24 hours remain before `trial_ends_at`; negative values indicate the trial has already expired.

This endpoint is consumed by the dashboard trial-expiry banner.

---

### Classes

| Method | Path | Description |
|---|---|---|
| GET | `/classes` | List all classes for the authenticated teacher |
| POST | `/classes` | Create a new class |
| GET | `/classes/{classId}` | Get class detail + enrollment summary |
| PATCH | `/classes/{classId}` | Update class name, subject, grade level |
| POST | `/classes/{classId}/archive` | Archive the class (soft) |
| GET | `/classes/{classId}/insights` | Class-level skill averages, score distributions, and common issues |
| GET | `/classes/{classId}/groups` | Current auto-generated skill-gap student groups for a class |
| PATCH | `/classes/{classId}/groups/{groupId}` | Manually adjust the student membership of a skill-gap group |

**GET /classes query params:** `?academic_year=2025-26&is_archived=false`

**GET /classes/{classId}/insights response (200):**
```json
{
  "data": {
    "class_id": "uuid",
    "assignment_count": 3,
    "student_count": 28,
    "graded_essay_count": 25,
    "skill_averages": {
      "evidence": { "avg_score": 0.55, "student_count": 25, "data_points": 75 },
      "thesis":   { "avg_score": 0.78, "student_count": 25, "data_points": 75 }
    },
    "score_distributions": {
      "evidence": [
        { "label": "0-20%",   "count": 3 },
        { "label": "20-40%",  "count": 7 },
        { "label": "40-60%",  "count": 9 },
        { "label": "60-80%",  "count": 5 },
        { "label": "80-100%", "count": 1 }
      ],
      "thesis": [
        { "label": "0-20%",   "count": 0 },
        { "label": "20-40%",  "count": 2 },
        { "label": "40-60%",  "count": 5 },
        { "label": "60-80%",  "count": 12 },
        { "label": "80-100%", "count": 6 }
      ]
    },
    "common_issues": [
      { "skill_dimension": "evidence", "avg_score": 0.55, "affected_student_count": 14 }
    ]
  }
}
```
- `skill_averages` — keyed by canonical skill dimension (`thesis`, `evidence`, `organization`, `analysis`, `mechanics`, `voice`, `other`); `avg_score` is normalised to [0.0, 1.0].
- `score_distributions` — five 20-percentage-point buckets per skill, present for every dimension in `skill_averages`.
- `common_issues` — skill dimensions where the class average normalised score is below 0.60, sorted ascending by `avg_score` (worst first).
- Only **locked** grades contribute; unlocked grades are excluded.

Errors: `403 FORBIDDEN` (class belongs to another teacher), `404 NOT_FOUND` (class does not exist).

**GET /classes/{classId}/groups** (requires JWT)

Returns the current auto-generated skill-gap student groups for the class, computed by the auto-grouping Celery task each time a grade is locked.

```json
{
  "data": {
    "class_id": "uuid",
    "groups": [
      {
        "id": "uuid",
        "skill_key": "evidence",
        "label": "Evidence",
        "stability": "persistent",
        "student_count": 4,
        "students": [
          { "id": "uuid", "full_name": "Student Name", "external_id": null }
        ],
        "computed_at": "2026-04-29T18:00:00Z"
      },
      {
        "id": "uuid",
        "skill_key": "thesis",
        "label": "Thesis",
        "stability": "exited",
        "student_count": 0,
        "students": [],
        "computed_at": "2026-04-29T18:00:00Z"
      }
    ]
  }
}
```

- **`groups`** — ordered: active groups (`new`/`persistent`) first sorted by `label`; exited groups last sorted by `label`. Empty list when no groups have been computed yet.
- **`stability`** — lifecycle tag for each group:
  - `new` — first time this skill gap has appeared for the class.
  - `persistent` — the group existed in the previous computation run.
  - `exited` — previously existed but no longer meets the minimum group-size threshold; `students` is always empty for exited groups.
- **`students`** — resolved student summaries (name + optional external ID); empty for `exited` groups.
- **`computed_at`** — ISO-8601 timestamp of the computation run that produced this group.

Errors: `403 FORBIDDEN` (class belongs to another teacher), `404 NOT_FOUND` (class does not exist).

---

**PATCH /classes/{classId}/groups/{groupId}** (requires JWT)

Manually replaces the student membership of a skill-gap group. The supplied `student_ids` list becomes the new membership in full. Duplicate student IDs are removed while preserving the submitted order of the resulting membership list. The returned `students` array is sorted by `full_name` for deterministic UI ordering and therefore does not necessarily match the submitted order. An empty list transitions the group to `stability='exited'`.

**Request body:**
```json
{
  "student_ids": ["uuid", "uuid"]
}
```

**Response (200):**
```json
{
  "data": {
    "id": "uuid",
    "skill_key": "evidence",
    "label": "Evidence",
    "student_count": 2,
    "students": [
      { "id": "uuid", "full_name": "Student Name", "external_id": null }
    ],
    "stability": "persistent",
    "computed_at": "2026-01-01T00:00:00Z"
  }
}
```

Stability transitions on update:
- Empty list → `exited`
- Previously `exited` + non-empty list → `persistent`
- Otherwise, the existing stability value is preserved.

Note: This endpoint adjusts only the group record; it does not modify the underlying `StudentSkillProfile` data.

Errors: `403 FORBIDDEN` (class belongs to another teacher), `404 NOT_FOUND` (class or group does not exist), `422 UNPROCESSABLE_ENTITY` (invalid request body).

---

### Students

| Method | Path | Description |
|---|---|---|
| GET | `/classes/{classId}/students` | List enrolled students in a class |
| POST | `/classes/{classId}/students` | Enroll a new or existing student |
| POST | `/classes/{classId}/students/import` | Parse a CSV roster and return an import diff (no DB write) |
| POST | `/classes/{classId}/students/import/confirm` | Commit a reviewed CSV roster import |
| DELETE | `/classes/{classId}/students/{studentId}` | Remove student from class (soft) |
| GET | `/students/{studentId}` | Get student detail + skill profile |
| GET | `/students/{studentId}/history` | Get all graded assignments for a student |
| PATCH | `/students/{studentId}` | Update student name, external ID, or private teacher notes |

#### CSV Roster Import Flow

Two-phase import prevents accidental bulk writes:

1. **`POST /classes/{classId}/students/import`** — multipart CSV upload (`file` field).
   - Accepted columns: `full_name` (required, case-insensitive), `external_id` (optional).
   - Returns a diff with per-row status and aggregate counts; **no students are written to the DB**.
   - Returns `422` if the CSV is malformed, missing the `full_name` column, or exceeds 200 rows.
   - Individual rows with an empty `full_name` appear in the diff with `status: "error"`.

2. **`POST /classes/{classId}/students/import/confirm`** — JSON body `{ "rows": [...] }`.
   - Teacher sends back only the rows they approve (may omit skipped/error rows).
   - Server re-validates each row against the current roster before writing.
   - Returns `{ "data": { "created": N, "updated": N, "skipped": N } }`.

**Per-row statuses:**

| Status | Meaning |
|---|---|
| `new` | No match found; a new student record will be created and enrolled |
| `updated` | Existing student matched by `external_id` (not currently enrolled); will be enrolled |
| `skipped` | Already enrolled, or fuzzy name match detected — no change will be made |
| `error` | Row failed validation (e.g. missing `full_name`); excluded from commit |

---

### Rubrics

| Method | Path | Description |
|---|---|---|
| GET | `/rubrics` | List teacher's rubrics |
| POST | `/rubrics` | Create a new rubric |
| GET | `/rubrics/{rubricId}` | Get rubric with all criteria |
| PATCH | `/rubrics/{rubricId}` | Update rubric metadata or criteria |
| DELETE | `/rubrics/{rubricId}` | Soft-delete rubric (blocked if in use by an open assignment) |
| POST | `/rubrics/{rubricId}/duplicate` | Duplicate rubric as a new draft |

---

### Rubric Templates

System starter templates (seeded via migration) and teacher-owned personal templates.
System templates have `is_system: true` (`teacher_id IS NULL`); personal templates have `is_system: false`.

| Method | Path | Description |
|---|---|---|
| GET | `/rubric-templates` | List system + teacher's personal templates |
| GET | `/rubric-templates/{templateId}` | Get a single template with full criteria |
| POST | `/rubric-templates` | Save a rubric as a personal template |

**GET /rubric-templates response:**
```json
{
  "data": [
    {
      "id": "uuid",
      "name": "5-Paragraph Essay",
      "description": "A starter template for five-paragraph essays.",
      "is_system": true,
      "created_at": "2026-04-20T00:00:00Z",
      "updated_at": "2026-04-20T00:00:00Z",
      "criterion_count": 4
    }
  ]
}
```

**POST /rubric-templates body:**
```json
{
  "rubric_id": "uuid-of-source-rubric",
  "name": "Optional override name"
}
```

**POST /rubric-templates response (201):**
```json
{
  "data": {
    "id": "uuid",
    "name": "My Template",
    "description": "...",
    "is_system": false,
    "created_at": "2026-04-20T00:00:00Z",
    "updated_at": "2026-04-20T00:00:00Z",
    "criteria": [...]
  }
}
```

Errors: `404 NOT_FOUND` (source rubric not found), `403 FORBIDDEN` (source rubric belongs to another teacher).

**GET /rubric-templates/{templateId} response (200):**
Returns the same shape as `POST /rubric-templates` response but for any template.
System templates are accessible to any authenticated teacher; personal templates return `403` if accessed by a different teacher.

---

### Comment Bank

| Method | Path | Description |
|---|---|---|
| GET | `/comment-bank` | List the authenticated teacher's saved comments |
| POST | `/comment-bank` | Save a new feedback comment snippet |
| DELETE | `/comment-bank/{comment_id}` | Remove a saved comment |
| GET | `/comment-bank/suggestions` | Fuzzy-match suggestions for a query string |

**GET /comment-bank response (200):**
```json
{
  "data": [
    {
      "id": "uuid",
      "text": "Good use of textual evidence to support the argument.",
      "created_at": "2026-04-21T00:00:00Z"
    }
  ]
}
```

**POST /comment-bank body:**
```json
{ "text": "Good use of textual evidence to support the argument." }
```
`text` must be 1–2000 characters.

**POST /comment-bank response (201):** Same shape as a single item in the list response.

Errors: `403 FORBIDDEN` (delete — comment belongs to another teacher), `404 NOT_FOUND` (delete — comment does not exist).

**GET /comment-bank/suggestions query params:** `?q=<text>` (required, 1–500 characters)

**GET /comment-bank/suggestions response (200):**
```json
{
  "data": [
    {
      "id": "uuid",
      "text": "Good use of textual evidence.",
      "score": 0.9,
      "created_at": "2026-04-21T00:00:00Z"
    }
  ]
}
```
`score` is a normalised fuzzy-match score in the range 0.0–1.0. Results are ordered by descending score.
Suggestions are **advisory only** — the teacher explicitly selects which comment to apply.

---

**POST /rubrics body:**
```json
{
  "name": "5-Paragraph Essay",
  "criteria": [
    {
      "name": "Thesis Statement",
      "description": "Does the essay present a clear, arguable thesis?",
      "weight": 30,
      "min_score": 1,
      "max_score": 5,
      "anchor_descriptions": { "1": "No clear thesis.", "5": "Precise, arguable thesis that forecasts the essay." }
    }
  ]
}
```

---

### Assignments

| Method | Path | Description |
|---|---|---|
| GET | `/classes/{classId}/assignments` | List assignments for a class |
| POST | `/classes/{classId}/assignments` | Create assignment |
| GET | `/assignments/{assignmentId}` | Get assignment detail + submission status |
| PATCH | `/assignments/{assignmentId}` | Update title, prompt, due date, status, feedback tone, or resubmission setting |
| POST | `/assignments/{assignmentId}/grade` | Trigger grading for all queued essays |
| GET | `/assignments/{assignmentId}/grading-status` | Batch grading progress (polled by frontend) |
| POST | `/assignments/{assignmentId}/export` | Enqueue export job |
| GET | `/assignments/{assignmentId}/grades.csv` | Synchronous CSV gradebook export (locked grades only) |
| GET | `/assignments/{assignmentId}/analytics` | Score distribution, common issues, averages |

**POST /classes/{classId}/assignments body:**
```json
{
  "rubric_id": "uuid",
  "title": "Persuasive Essay — Unit 3",
  "prompt": "Write a 5-paragraph essay arguing your position.",
  "due_date": "2026-05-01",
  "feedback_tone": "direct"
}
```
`feedback_tone` controls the register of AI-generated per-criterion feedback notes and the summary paragraph.  One of `"encouraging"`, `"direct"` (default), `"academic"`.

**POST /classes/{classId}/assignments response (201):**
```json
{
  "data": {
    "id": "uuid",
    "class_id": "uuid",
    "rubric_id": "uuid",
    "rubric_snapshot": { "id": "...", "name": "...", "criteria": [...] },
    "title": "Persuasive Essay — Unit 3",
    "prompt": "Write a 5-paragraph essay arguing your position.",
    "due_date": "2026-05-01",
    "status": "draft",
    "feedback_tone": "direct",
    "resubmission_enabled": false,
    "resubmission_limit": null,
    "created_at": "2026-04-21T00:00:00Z"
  }
}
```

**PATCH /assignments/{assignmentId} body** (all fields optional — only provided fields are updated):
```json
{
  "title": "Updated Title",
  "prompt": "Updated prompt.",
  "due_date": "2026-05-15",
  "status": "open",
  "feedback_tone": "encouraging",
  "resubmission_enabled": true
}
```

**POST /assignments/{id}/grade body:**
```json
{
  "essay_ids": ["uuid1", "uuid2"],  // omit to grade all queued essays
  "strictness": "balanced"
}
```

**POST /assignments/{id}/grade response (202 Accepted):**
```json
{
  "data": {
    "enqueued": 28,
    "assignment_id": "uuid"
  }
}
```

**GET /assignments/{id}/grading-status response:**
```json
{
  "data": {
    "status": "processing",
    "total": 30,
    "complete": 12,
    "failed": 1,
    "essays": [
      { "id": "uuid", "status": "complete", "student_name": "Student A", "error": null },
      { "id": "uuid", "status": "failed", "student_name": "Student B", "error": "LLM_TIMEOUT" }
    ]
  }
}
```

**GET /assignments/{assignmentId}/grades.csv response (200):**
Returns a `text/csv` file download with header:
```
student_id,student_name,<criterion_name_1>,...,weighted_total
```
Criterion columns are ordered by `display_order` from the immutable rubric snapshot.  Only locked grades (`is_locked = true`) are included.  If no grades are locked, the response contains only the header row.  The `Content-Disposition` header is set to `attachment; filename="grades-<uuid>.csv"`.

> **Frontend note:** This endpoint returns `text/csv`, not the standard `{"data": ...}` JSON envelope, so it cannot be called via the shared `apiGet()` helper (which calls `response.json()`).  Use a dedicated helper that performs a `fetch()` with the normal `Authorization: Bearer ...` header and reads the response via `response.blob()` or `response.text()`.  If a browser-navigation-style download is required, expose a separate JSON endpoint that returns a short-lived pre-signed URL or one-time download token specifically for the export.  Do **not** place the access token in the URL or query string.

Errors: `403 FORBIDDEN` (assignment belongs to another teacher), `404 NOT_FOUND` (assignment does not exist).

**GET /assignments/{assignmentId}/analytics response (200):**
```json
{
  "data": {
    "assignment_id": "uuid",
    "class_id": "uuid",
    "total_essay_count": 28,
    "locked_essay_count": 25,
    "overall_avg_normalized_score": 0.72,
    "criterion_analytics": [
      {
        "criterion_id": "uuid",
        "criterion_name": "Thesis Statement",
        "skill_dimension": "thesis",
        "min_score_possible": 0,
        "max_score_possible": 5,
        "avg_score": 3.6,
        "avg_normalized_score": 0.72,
        "score_distribution": [
          { "score": 3, "count": 10 },
          { "score": 4, "count": 8 },
          { "score": 5, "count": 7 }
        ]
      }
    ]
  }
}
```
- `overall_avg_normalized_score` — mean normalised score across all criteria and all locked essays; `null` when no grades are locked.
- `criterion_analytics` — one entry per rubric criterion, ordered by `display_order` from the immutable rubric snapshot.
- `score_distribution` — count of essays per raw score value, ordered by ascending score.
- Only **locked** grades contribute.

Errors: `403 FORBIDDEN` (assignment belongs to another teacher), `404 NOT_FOUND` (assignment does not exist).

---

| Method | Path | Description |
|---|---|---|
| POST | `/assignments/{assignmentId}/essays` | Upload one or more essays |
| POST | `/assignments/{assignmentId}/essays/compose` | Create a blank essay for in-browser composition (M5-09) |
| GET | `/assignments/{assignmentId}/essays` | List essays with status and student assignment |
| GET | `/essays/{essayId}` | Get essay detail with current grade |
| PATCH | `/essays/{essayId}` | Assign to student (manual assignment) |
| POST | `/essays/{essayId}/resubmit` | Submit a new version (resubmission) |
| GET | `/essays/{essayId}/versions` | List all versions with grades |
| GET | `/essays/{essayId}/integrity` | Get integrity report |
| PATCH | `/integrity-reports/{reportId}/status` | Update teacher review status (`reviewed_clear` or `flagged`) |
| GET | `/assignments/{assignmentId}/integrity/summary` | Class-level integrity signal counts (flagged / clear / pending) |
| POST | `/essays/{essayId}/grade/retry` | Re-enqueue a single failed essay for grading |
| POST | `/essays/{essayId}/snapshots` | Save a writing-process snapshot (autosave, M5-09) |
| GET | `/essays/{essayId}/snapshots` | Retrieve writing snapshots for editor state recovery (M5-09) |
| GET | `/essays/{essayId}/process-signals` | Composition timeline and process signals (M5-10) |

**POST /assignments/{id}/essays** — multipart form:
- `files`: one or more files (PDF, DOCX, TXT); send each as a separate `files` part in the multipart body
- `student_id`: optional — if provided, all uploaded essays are immediately assigned to this student; only one file may be uploaded when `student_id` is set

MIME type is validated server-side from file magic bytes (not the file extension). File size limit is enforced before further processing (`MAX_ESSAY_FILE_SIZE_MB`, default 10 MB); the upload handler reads at most the configured limit plus one byte to detect oversize files without loading the entire upload into memory. The raw file is uploaded to S3 before text extraction so the original is preserved even if extraction fails.

**POST /assignments/{id}/essays response (201):**
```json
{
  "data": [
    {
      "essay_id": "uuid",
      "essay_version_id": "uuid",
      "assignment_id": "uuid",
      "student_id": null,
      "status": "unassigned",
      "word_count": 412,
      "file_storage_key": "essays/{assignmentId}/{essayId}/filename.pdf",
      "submitted_at": "2026-04-20T18:00:00Z",
      "auto_assign_status": "unassigned"
    }
  ]
}
```

`auto_assign_status` reflects the outcome of the auto-assignment attempt: `"assigned"` (essay matched to exactly one student with confidence ≥ 0.85), `"ambiguous"` (multiple students matched — held for manual review), or `"unassigned"` (no match found). When `student_id` is explicitly provided in the request this field is `null` (no roster search is performed).

Errors: `404 NOT_FOUND` (assignment not found, or student not found for this teacher), `403 FORBIDDEN` (assignment belongs to another teacher, or student not enrolled in the class), `422 VALIDATION_ERROR` (no files, more than one file with `student_id`, invalid MIME type, or file too large — `error.code` is `FILE_TYPE_NOT_ALLOWED`, `FILE_TOO_LARGE`, or `VALIDATION_ERROR` as appropriate).

**POST /essays/{essayId}/grade/retry body:**
```json
{
  "strictness": "balanced"  // optional; "lenient" | "balanced" | "strict"
}
```

Re-enqueues a single essay for grading. Only available when the essay has `status=queued` (essays fail and are reverted to `queued` after exhausting retries). Returns `202` immediately.

Errors: `403 FORBIDDEN` (essay belongs to another teacher), `404 NOT_FOUND` (essay not found), `409 CONFLICT` (essay is currently being graded or has already been completed).

**POST /assignments/{id}/essays/compose** — JSON body (M5-09):
```json
{
  "student_id": null
}
```
- `student_id`: optional — if provided, the new essay is immediately assigned to this student (must be enrolled in the assignment's class)

Creates a blank `Essay` and `EssayVersion` (empty content, `writing_snapshots: []`) without a file upload. The client then drives composition via the snapshot endpoints below.

**POST /assignments/{id}/essays/compose response (201):**
```json
{
  "data": {
    "essay_id": "uuid",
    "essay_version_id": "uuid",
    "assignment_id": "uuid",
    "student_id": null,
    "status": "unassigned",
    "current_content": "",
    "word_count": 0
  }
}
```

Errors: `403 FORBIDDEN` (assignment belongs to another teacher, or student not enrolled), `404 NOT_FOUND` (assignment or student not found).

**POST /essays/{essayId}/snapshots** — JSON body (M5-09):
```json
{
  "html_content": "<p>Essay text…</p>",
  "word_count": 150
}
```
- `html_content`: raw innerHTML from the browser editor (max 500 000 characters); stored in `writing_snapshots` JSONB and also stripped to plain text for the LLM pipeline
- `word_count`: pre-computed by the client (HTML tags stripped, split on whitespace)

Each call appends a snapshot entry `{seq, ts, word_count, html_content}` to the version's `writing_snapshots` array and updates `EssayVersion.content` (plain text) and `word_count`. Called by the browser autosave every 10–15 seconds of user activity.

**POST /essays/{essayId}/snapshots response (200):**
```json
{
  "data": {
    "essay_id": "uuid",
    "essay_version_id": "uuid",
    "snapshot_count": 3,
    "word_count": 150,
    "saved_at": "2026-04-28T10:00:12+00:00"
  }
}
```

Errors: `403 FORBIDDEN` (essay belongs to another teacher), `404 NOT_FOUND` (essay or version not found), `422 VALIDATION_ERROR` (`html_content` missing or exceeds 500 000 characters).

**GET /essays/{essayId}/snapshots response (200)** (M5-09):
```json
{
  "data": {
    "essay_id": "uuid",
    "essay_version_id": "uuid",
    "current_content": "<p>Essay text…</p>",
    "word_count": 150,
    "snapshots": [
      {"seq": 1, "ts": "2026-04-28T10:00:00+00:00", "word_count": 50},
      {"seq": 2, "ts": "2026-04-28T10:00:12+00:00", "word_count": 100},
      {"seq": 3, "ts": "2026-04-28T10:00:24+00:00", "word_count": 150}
    ]
  }
}
```

`current_content` is the `html_content` of the most recent snapshot — ready to inject directly into the browser editor for state recovery after a page refresh. Individual `html_content` values of earlier snapshots are not returned here; they are used by the writing-process timeline (M5-10/11). This endpoint is only valid for browser-composed essays. File-upload essays (where `writing_snapshots` is `NULL`) return `422 VALIDATION_ERROR` because there is no snapshot-backed editor state to recover. Errors: `403 FORBIDDEN`, `404 NOT_FOUND`, `422 VALIDATION_ERROR` (essay has no writing snapshots — was created via file upload).

**GET /essays/{essayId}/process-signals response (200)** (M5-10):
```json
{
  "data": {
    "essay_id": "uuid",
    "essay_version_id": "uuid",
    "has_process_data": true,
    "session_count": 2,
    "active_writing_seconds": 1800.0,
    "total_elapsed_seconds": 90000.0,
    "inter_session_gaps_seconds": [88200.0],
    "sessions": [
      {
        "session_index": 0,
        "started_at": "2026-04-28T09:00:00+00:00",
        "ended_at": "2026-04-28T09:15:00+00:00",
        "duration_seconds": 900.0,
        "snapshot_count": 12,
        "word_count_start": 0,
        "word_count_end": 250,
        "words_added": 250
      }
    ],
    "paste_events": [
      {
        "snapshot_seq": 4,
        "occurred_at": "2026-04-28T09:05:00+00:00",
        "words_before": 50,
        "words_after": 250,
        "words_added": 200,
        "session_index": 0
      }
    ],
    "rapid_completion_events": [],
    "computed_at": "2026-04-28T10:30:00+00:00"
  }
}
```

Signals are computed lazily on first request and cached in `EssayVersion.process_signals`. The cache is automatically invalidated when new snapshots are added (detected by comparing snapshot counts). When `has_process_data` is `false`, no usable writing-process data was available for that essay version — for example, the essay may have been submitted via file upload, the snapshot list may be empty, or the stored snapshots may be entirely unparseable. In that case, all list fields are empty and numeric metrics are zero. `paste_events` and `rapid_completion_events` are informational signals for teacher review, not definitive findings — they should always be presented with appropriate context. Errors: `403 FORBIDDEN`, `404 NOT_FOUND`.

---

### Grades

| Method | Path | Description |
|---|---|---|
| GET | `/essays/{essayId}/grade` | Get current grade with all criterion scores |
| PATCH | `/grades/{gradeId}/feedback` | Edit summary feedback text |
| PATCH | `/grades/{gradeId}/criteria/{criterionId}` | Override a criterion score or feedback |
| POST | `/grades/{gradeId}/lock` | Lock grade as final |
| GET | `/grades/{gradeId}/audit` | View audit log for this grade |
| POST | `/grades/{gradeId}/regrade-requests` | Submit a regrade request for a grade |
| GET | `/assignments/{assignmentId}/regrade-requests` | List all regrade requests for an assignment |
| POST | `/regrade-requests/{requestId}/resolve` | Approve or deny a regrade request |

**GET /essays/{essayId}/grade response (200):**
```json
{
  "data": {
    "id": "uuid",
    "essay_version_id": "uuid",
    "total_score": "7.00",
    "max_possible_score": "10.00",
    "summary_feedback": "Overall AI-generated feedback.",
    "summary_feedback_edited": null,
    "strictness": "balanced",
    "ai_model": "gpt-4o",
    "prompt_version": "grading-v2",
    "is_locked": false,
    "locked_at": null,
    "overall_confidence": "high",
    "created_at": "2026-04-01T00:00:00Z",
    "criterion_scores": [
      {
        "id": "uuid",
        "rubric_criterion_id": "uuid",
        "ai_score": 4,
        "teacher_score": null,
        "final_score": 4,
        "ai_justification": "The essay clearly states a thesis...",
        "ai_feedback": "Strong thesis — try to connect it more explicitly to your evidence.",
        "teacher_feedback": null,
        "confidence": "high",
        "created_at": "2026-04-01T00:00:00Z"
      }
    ]
  }
}
```

`overall_confidence` is derived from the constituent criterion scores: `"low"` if any criterion is `"low"`; `"medium"` if any is `"medium"` (and none is `"low"`); `"high"` if all are `"high"`. `null` for grades produced before M4.1.

**PATCH /grades/{id}/criteria/{criterionId} body:**
```json
{
  "teacher_score": 4,
  "teacher_feedback": "Strong evidence, but the connection to the thesis could be more explicit."
}
```

---

### Exports

| Method | Path | Description |
|---|---|---|
| POST | `/assignments/{assignmentId}/export` | Enqueue PDF batch export (202) |
| GET | `/exports/{taskId}/status` | Poll export job status |
| GET | `/exports/{taskId}/download` | Get pre-signed S3 download URL |

**POST /assignments/{assignmentId}/export response (202):**
```json
{
  "data": {
    "task_id": "uuid",
    "assignment_id": "uuid",
    "status": "pending"
  }
}
```

Only locked grades are included. Returns 404 if the assignment does not exist, 403 if it belongs to a different teacher.

**GET /exports/{taskId}/status response (200):**
```json
{
  "data": {
    "task_id": "uuid",
    "status": "processing",
    "total": 30,
    "complete": 12,
    "error": null
  }
}
```

`status` is one of `pending | processing | complete | failed`. Returns 404 if the task is not found, 403 if it belongs to a different teacher.

**GET /exports/{taskId}/download response (200):**
```json
{
  "data": {
    "url": "https://s3.example.com/exports/…?X-Amz-Expires=900&…",
    "expires_in_seconds": 900
  }
}
```

The pre-signed URL is valid for 15 minutes. Returns 409 if the export is not yet complete, 404 if not found, 403 if cross-teacher access.

---

### Instruction Recommendations

| Method | Path | Description |
|---|---|---|
| POST | `/students/{studentId}/recommendations` | Generate AI instruction recommendations from a student's skill profile |
| GET | `/students/{studentId}/recommendations` | List persisted recommendation sets for a student (newest-first) |
| POST | `/classes/{classId}/groups/{groupId}/recommendations` | Generate AI recommendations targeting a class skill-gap group |
| POST | `/recommendations/{recommendationId}/assign` | Teacher-confirmed assignment of an instruction recommendation (human-in-the-loop) |

**POST /students/{studentId}/recommendations body:**
```json
{
  "grade_level": "Grade 8",
  "duration_minutes": 20,
  "skill_key": "evidence",
  "worklist_item_id": "uuid"
}
```

`skill_key` and `worklist_item_id` are optional.  `duration_minutes` must be between 5 and 120.

**POST /students/{studentId}/recommendations response (201):**
```json
{
  "data": {
    "id": "uuid",
    "teacher_id": "uuid",
    "student_id": "uuid",
    "group_id": null,
    "worklist_item_id": null,
    "skill_key": "evidence",
    "grade_level": "Grade 8",
    "prompt_version": "instruction-v1",
    "recommendations": [
      {
        "skill_dimension": "evidence",
        "title": "Evidence Workshop",
        "description": "Practice integrating and citing evidence.",
        "estimated_minutes": 20,
        "strategy_type": "guided_practice"
      }
    ],
    "evidence_summary": "Skill gap in 'evidence': average score 40%, trend stable.",
    "status": "pending_review",
    "created_at": "2026-04-30T00:00:00Z"
  }
}
```

Returns 404 if the student does not exist, 403 if it belongs to a different teacher, 422 if the student has no skill profile data or the request body is invalid, 503 if the LLM is unavailable.

**POST /classes/{classId}/groups/{groupId}/recommendations** — identical body and response shape.  Returns 404 if the group or class does not exist, 403 if cross-teacher access.

**POST /recommendations/{recommendationId}/assign response (200):**
```json
{
  "data": {
    "id": "uuid",
    "status": "accepted",
    ...
  }
}
```

Transitions the recommendation from `pending_review` → `accepted`.  Idempotent when already `accepted`.  Returns 404 if the recommendation does not exist or belongs to a different teacher (indistinguishable under FORCE RLS), 409 if it is in `dismissed` state.

---

### Worklist

| Method | Path | Description |
|---|---|---|
| GET | `/worklist` | Get prioritized teacher worklist |
| POST | `/worklist/{itemId}/complete` | Mark worklist item as done |
| POST | `/worklist/{itemId}/snooze` | Snooze item (defer to next week) |
| DELETE | `/worklist/{itemId}` | Dismiss item permanently |

---

### Contact (Public — no authentication required)

| Method | Path | Description |
|---|---|---|
| POST | `/contact/inquiry` | Submit a school or district purchase inquiry |
| POST | `/contact/dpa-request` | Submit a Data Processing Agreement (DPA) request |

**POST /contact/inquiry body:**
```json
{
  "name": "Jane Smith",
  "email": "jane@example-school.edu",
  "school_name": "Example High School",
  "district": "Example Unified",
  "estimated_teachers": 40,
  "message": "We are interested in the School tier."
}
```

Fields `district`, `estimated_teachers`, and `message` are optional.

**POST /contact/inquiry response (201):**
```json
{
  "data": {
    "id": "uuid",
    "created_at": "2025-01-01T00:00:00Z"
  }
}
```

**Rate limiting:** Maximum 5 submissions per IP address per hour. Excess requests return `429 RATE_LIMITED`.

**Error codes specific to this endpoint:**

| Code | HTTP Status | When raised |
|---|---|---|
| `RATE_LIMITED` | 429 | Submitter IP has exceeded 5 inquiries per hour |

---

**POST /contact/dpa-request body:**
```json
{
  "name": "Jane Smith",
  "email": "jane@district.edu",
  "school_name": "Example Unified School District",
  "district": "Example Unified",
  "message": "We use the SDPC model DPA — please review and sign."
}
```

Fields `district` and `message` are optional. No student PII is collected.

**POST /contact/dpa-request response (201):**
```json
{
  "data": {
    "id": "uuid",
    "created_at": "2025-01-01T00:00:00Z"
  }
}
```

**Rate limiting:** Maximum 3 submissions per IP address per hour (stricter than inquiry — DPA requests are expected to be rare). Excess requests return `429 RATE_LIMITED`.

**Error codes specific to this endpoint:**

| Code | HTTP Status | When raised |
|---|---|---|
| `RATE_LIMITED` | 429 | Submitter IP has exceeded 3 DPA requests per hour |

---

## Error Codes

All errors use this envelope — the `field` key is only present on validation errors:

```json
{
  "error": {
    "code": "GRADE_LOCKED",
    "message": "This grade has been locked and cannot be edited.",
    "field": null
  }
}
```

Error `code` values are `SCREAMING_SNAKE_CASE` strings. The frontend should branch on `code`, not `message` — messages are for humans and may change.

### Authentication & Authorization

| Code | HTTP Status | When raised |
|---|---|---|
| `UNAUTHORIZED` | 401 | Missing, expired, or malformed JWT token |
| `FORBIDDEN` | 403 | Valid token but resource belongs to a different teacher |
| `TOKEN_EXPIRED` | 401 | Access token has expired — client should refresh |
| `REFRESH_TOKEN_INVALID` | 401 | Refresh token is expired, revoked, or not found |

### Resource Not Found

| Code | HTTP Status | When raised |
|---|---|---|
| `NOT_FOUND` | 404 | Generic — resource does not exist (use specific codes below where possible) |
| `CLASS_NOT_FOUND` | 404 | Class ID does not exist or belongs to another teacher |
| `STUDENT_NOT_FOUND` | 404 | Student ID does not exist or is not enrolled in the class |
| `ASSIGNMENT_NOT_FOUND` | 404 | Assignment ID does not exist or belongs to another teacher |
| `ESSAY_NOT_FOUND` | 404 | Essay ID does not exist or belongs to another teacher |
| `GRADE_NOT_FOUND` | 404 | Grade record does not exist for this essay version |
| `RUBRIC_NOT_FOUND` | 404 | Rubric ID does not exist or belongs to another teacher |
| `EXPORT_NOT_FOUND` | 404 | Export task ID does not exist |

### Validation Errors (422)

| Code | HTTP Status | When raised |
|---|---|---|
| `VALIDATION_ERROR` | 422 | Generic Pydantic validation failure — `field` is set to the offending field name |
| `RUBRIC_WEIGHT_INVALID` | 422 | Criterion weights do not sum to 100 |
| `RUBRIC_SCORE_RANGE_INVALID` | 422 | `min_score` ≥ `max_score` on a criterion |
| `RUBRIC_NO_CRITERIA` | 422 | Rubric has no criteria |
| `FILE_TYPE_NOT_ALLOWED` | 422 | Uploaded file MIME type is not PDF, DOCX, or TXT |
| `FILE_TOO_LARGE` | 422 | File exceeds `MAX_ESSAY_FILE_SIZE_MB` |
| `BATCH_TOO_LARGE` | 422 | More than `MAX_BATCH_SIZE` essays in a single grading request |
| `STUDENT_ALREADY_ENROLLED` | 422 | Student is already enrolled in this class |

### Conflict Errors (409)

| Code | HTTP Status | When raised |
|---|---|---|
| `GRADE_LOCKED` | 409 | Attempted to edit or delete a locked grade |
| `GRADING_IN_PROGRESS` | 409 | Grading already running for this assignment — cannot start another |
| `ASSIGNMENT_NOT_GRADEABLE` | 409 | Assignment is in a state that does not permit grading (e.g., archived, no essays) |
| `RUBRIC_IN_USE` | 409 | Cannot delete a rubric that is attached to an open assignment |
| `ESSAY_ALREADY_GRADED` | 409 | Essay already has a locked grade — submit a resubmission instead |

### Rate Limit Errors (429)

| Code | HTTP Status | When raised |
|---|---|---|
| `RATE_LIMITED` | 429 | Request rate limit exceeded for the caller's IP (e.g. contact inquiry endpoint) |

### Server & Upstream Errors (5xx)

| Code | HTTP Status | When raised |
|---|---|---|
| `LLM_UNAVAILABLE` | 503 | OpenAI API is unreachable or returned a 5xx — client should retry |
| `LLM_PARSE_ERROR` | 500 | LLM returned a response that failed schema validation after retries |
| `EXPORT_FAILED` | 500 | Export task failed — see `/exports/{taskId}/status` for detail |
| `FILE_EXTRACTION_FAILED` | 500 | Text could not be extracted from the uploaded file |
| `INTERNAL_ERROR` | 500 | Unexpected server error — check backend logs |

---

## Versioning

The API is versioned at the URL level (`/api/v1`). Breaking changes require a new version prefix. Non-breaking additions (new fields, new optional params) do not require a version bump. The frontend and backend are deployed together — tight versioning is not required at this stage, but the prefix is established now to avoid painful retrofitting later.
