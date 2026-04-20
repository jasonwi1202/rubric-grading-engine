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

**GET /classes query params:** `?academic_year=2025-26&is_archived=false`

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
| PATCH | `/students/{studentId}` | Update student name or external ID |

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
| PATCH | `/assignments/{assignmentId}` | Update title, prompt, due date, rubric (draft only) |
| POST | `/assignments/{assignmentId}/grade` | Trigger grading for all queued essays |
| GET | `/assignments/{assignmentId}/grading-status` | Batch grading progress (polled by frontend) |
| POST | `/assignments/{assignmentId}/export` | Enqueue export job |
| GET | `/assignments/{assignmentId}/analytics` | Score distribution, common issues, averages |

**POST /assignments/{id}/grade body:**
```json
{
  "essay_ids": ["uuid1", "uuid2"],  // omit to grade all queued essays
  "strictness": "balanced"
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
      { "id": "uuid", "status": "graded", "student_name": "Alice Chen" },
      { "id": "uuid", "status": "failed", "error": "LLM_TIMEOUT" }
    ]
  }
}
```

---

### Essays

| Method | Path | Description |
|---|---|---|
| POST | `/assignments/{assignmentId}/essays` | Upload one or more essays |
| GET | `/assignments/{assignmentId}/essays` | List essays with status and student assignment |
| GET | `/essays/{essayId}` | Get essay detail with current grade |
| PATCH | `/essays/{essayId}` | Assign to student (manual assignment) |
| POST | `/essays/{essayId}/resubmit` | Submit a new version (resubmission) |
| GET | `/essays/{essayId}/versions` | List all versions with grades |
| GET | `/essays/{essayId}/integrity` | Get integrity report |

**POST /assignments/{id}/essays** — multipart form:
- `files`: one or more files (PDF, DOCX, TXT); send each as a separate `files` part in the multipart body
- `student_id`: optional — if provided, all uploaded essays are immediately assigned to this student; only one file may be uploaded when `student_id` is set

MIME type is validated server-side from file magic bytes (not the file extension). File size limit is enforced before reading file content (`MAX_ESSAY_FILE_SIZE_MB`, default 10 MB). The raw file is uploaded to S3 before text extraction so the original is preserved even if extraction fails.

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
      "submitted_at": "2026-04-20T18:00:00Z"
    }
  ]
}
```

Errors: `404 NOT_FOUND` (assignment not found, or student not found for this teacher), `403 FORBIDDEN` (assignment belongs to another teacher, or student not enrolled in the class), `422 VALIDATION_ERROR` (no files, more than one file with `student_id`, invalid MIME type, or file too large — `error.code` is `FILE_TYPE_NOT_ALLOWED`, `FILE_TOO_LARGE`, or `VALIDATION_ERROR` as appropriate).

---

### Grades

| Method | Path | Description |
|---|---|---|
| GET | `/essays/{essayId}/grade` | Get current grade with all criterion scores |
| PATCH | `/grades/{gradeId}/feedback` | Edit summary feedback text |
| PATCH | `/grades/{gradeId}/criteria/{criterionId}` | Override a criterion score or feedback |
| POST | `/grades/{gradeId}/lock` | Lock grade as final |
| GET | `/grades/{gradeId}/audit` | View audit log for this grade |

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
| GET | `/exports/{taskId}/status` | Poll export job status |
| GET | `/exports/{taskId}/download` | Get pre-signed S3 download URL |

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
