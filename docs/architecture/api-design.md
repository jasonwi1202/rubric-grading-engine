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

**GET /auth/verify-email query params:** `?token=<hmac_signed_token>`  
Consumes a single-use HMAC-SHA256 token (24 h TTL). Returns `200` on success, `422` for invalid/expired token.

**POST /auth/resend-verification body:**
```json
{ "email": "teacher@school.edu" }
```
Always returns `202` regardless of whether the email is registered (avoids account-existence oracle).  
Returns `429` if more than 3 resend requests are made for the same email in one hour.

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
| DELETE | `/classes/{classId}/students/{studentId}` | Remove student from class (soft) |
| GET | `/students/{studentId}` | Get student detail + skill profile |
| GET | `/students/{studentId}/history` | Get all graded assignments for a student |
| PATCH | `/students/{studentId}` | Update student name or external ID |

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
- `files[]`: one or more files (PDF, DOCX, TXT)
- `text`: raw text (alternative to file upload)
- `student_id`: optional — skip auto-assignment

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
