# Data Flow

## Overview

This document traces how data moves through the system for the core workflows. Understanding these flows is essential before building any new feature — most bugs and performance issues originate at flow boundaries.

---

## Flow 1: Essay Submission and Grading

The primary workflow. Teacher uploads essays, triggers grading, reviews results.

```
1. Teacher uploads essay file(s) via Next.js UI
        │
        ▼
2. POST /assignments/{id}/essays  (FastAPI)
   - Validate file type and size
   - Extract text from PDF/DOCX (synchronous, fast)
   - Store raw file → S3
   - Create Essay + EssayVersion records (status: unassigned or queued)
   - Attempt auto-assignment to student roster
   - Return essay IDs to frontend
        │
        ▼
3. Teacher reviews auto-assignments, resolves unassigned essays
        │
        ▼
4. Teacher triggers grading: POST /assignments/{id}/grade
   - FastAPI validates assignment is in gradeable state
   - Enqueues one Celery grading task per essay
   - Updates assignment status → grading
   - Returns immediately (202 Accepted)
        │
        ▼
5. Celery grading worker picks up task
   - Loads essay text, rubric snapshot, and strictness config
   - Calls integrity check (async, parallel task)
   - Constructs grading prompt from rubric + essay
   - Calls LLM API (OpenAI)
   - Parses structured response: per-criterion scores + justifications
   - Writes Grade + CriterionScore records to Postgres
   - Updates essay status → graded
   - Updates batch progress counter in Redis
        │
        ▼
6. Frontend polls GET /assignments/{id}/grading-status every 3 seconds
   - FastAPI reads progress from Redis
   - Returns: {total, complete, failed, essays: [{id, status}]}
   - Frontend updates progress bar in real time
        │
        ▼
7. Grading complete → assignment status → review
   - Teacher opens review queue
   - GET /assignments/{id}/essays returns all graded essays with scores
        │
        ▼
8. Teacher reviews, overrides scores, edits feedback
   - PATCH /grades/{id}/criteria/{criterionId} for score overrides
   - PATCH /grades/{id}/feedback for feedback edits
   - Each change writes to CriterionScore or Grade
   - Each change appends to AuditLog
        │
        ▼
9. Teacher locks grade: POST /grades/{id}/lock
   - Sets Grade.is_locked = true
   - Triggers StudentSkillProfile update (async Celery task)
   - AuditLog entry written
```

---

## Flow 2: Student Skill Profile Update

Triggered after a grade is locked. Updates the student's persistent skill profile.

```
1. Grade locked event → Celery task enqueued

2. Task loads all locked CriterionScores for the student across all assignments
   - Normalizes criterion names to canonical skill dimensions
     (e.g., "Thesis Statement" → "thesis", "Evidence Use" → "evidence")

3. Computes aggregated skill scores:
   - Weighted average per skill dimension (recent assignments weighted higher)
   - Trend direction per skill (improving / stable / declining)
   - Data point count per skill

4. Upserts StudentSkillProfile.skill_scores (JSONB)

5. Triggers auto-grouping recalculation for the student's active classes
   (separate task — reads profiles, rebuilds groups)
```

---

## Flow 3: Batch Export

Teacher exports graded feedback as PDFs.

```
1. Teacher requests export: POST /assignments/{id}/export
   - Payload: {format: "pdf", student_ids: [...] | "all"}
   - FastAPI enqueues export Celery task
   - Returns task_id immediately

2. Celery export worker:
   - Loads all locked grades + feedback for requested students
   - Generates PDF per student (formatted template)
   - Packages into ZIP if multiple students
   - Uploads ZIP to S3
   - Writes download URL to Redis keyed by task_id (TTL: 1 hour)

3. Frontend polls GET /exports/{task_id}/status
   - Returns: {status: "complete", download_url: "..."}

4. Teacher downloads file directly from S3 pre-signed URL
   - FastAPI generates a short-lived pre-signed URL on request
   - File is never streamed through FastAPI
```

---

## Flow 4: Integrity Check

Runs in parallel with grading. Results are available when the teacher opens the review queue.

```
1. Integrity Celery task enqueued alongside grading task (same trigger)

2. Worker calls third-party integrity API with essay text
   - AI likelihood score
   - Similarity score + matched passages

3. Worker also runs internal cross-submission comparison:
   - Computes embedding for essay text (via LLM embeddings API)
   - Stores embedding in pgvector column on EssayVersion
   - Queries for similar essays within the same assignment using cosine similarity
   - Flags any pair with similarity above threshold

4. Writes IntegrityReport record to Postgres

5. Essay review UI displays integrity indicators alongside grading results
   - Teacher sees both grading and integrity data in a single view
```

---

## Flow 5: Authentication

```
1. POST /auth/login
   - Validate credentials
   - Issue JWT access token (15 min TTL, signed)
   - Set httpOnly refresh token cookie (7 day TTL)
   - Return access token in response body

2. Every authenticated request:
   - Next.js attaches access token as Bearer header
   - FastAPI validates JWT signature and expiry
   - Extracts teacher_id from token claims
   - All downstream queries are scoped to that teacher_id

3. Access token expiry:
   - API client receives 401
   - Silently calls POST /auth/refresh with refresh cookie
   - Backend validates refresh token, issues new access token
   - Original request retried with new token

4. Logout: POST /auth/logout
   - Refresh token invalidated server-side (stored in Redis with TTL)
   - httpOnly cookie cleared
```

---

## Data Boundaries

| Data | Stored In | Notes |
|---|---|---|
| Essay text | PostgreSQL (EssayVersion.content) | Kept in DB for query simplicity |
| Raw uploaded files | S3 | PDFs, DOCX — referenced by storage key |
| Exported ZIPs / PDFs | S3 | Temporary, short-lived pre-signed URLs |
| Media comments (audio/video) | S3 | Permanent, access-controlled |
| Grading task state | Redis | TTL — cleaned up after completion |
| Batch progress counters | Redis | TTL — per assignment, while grading runs |
| Essay embeddings | PostgreSQL (pgvector) | In EssayVersion for similarity queries |
| Audit log | PostgreSQL | Append-only, never deleted |
| Session / refresh tokens | Redis | Short TTL for access tokens |

---

## Error States and Recovery

| Failure Point | Behavior |
|---|---|
| LLM API timeout during grading | Celery retries up to 3 times with exponential backoff. After max retries, essay status → `failed`. Teacher sees error in review queue and can manually re-trigger. |
| Integrity API unavailable | Integrity check is non-blocking. If it fails, essay proceeds to review queue without an integrity report. Teacher is notified the report is unavailable. |
| Celery worker crash mid-batch | Tasks are acknowledged only on completion. Unacknowledged tasks are requeued when worker restarts. Idempotency on task execution prevents duplicate grades. |
| Export generation failure | Export task fails; teacher sees error and can retry. No partial ZIPs are delivered. |
| S3 upload failure | File upload fails fast; no Essay record is created. Teacher is shown an upload error immediately. |
