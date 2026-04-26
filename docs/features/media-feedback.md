# Feature: Media Feedback

**Phase:** 2 — Workflow
**Status:** Partially Implemented (M4.10, M4.11, M4.12)

**Shipped (M4.10 — audio comments):**
- In-browser audio recording via MediaRecorder API with a 3-minute max and live countdown (`AudioRecorder` component in `EssayReviewPanel`)
- Post-recording preview playback before saving — teacher can discard and re-record
- `POST /grades/{id}/media-comments` — multipart upload → S3 → `media_comments` DB record
- `GET /grades/{id}/media-comments` — list all audio comments for a grade
- `DELETE /media-comments/{id}` — removes DB row and S3 object
- `GET /media-comments/{id}/url` — returns access-controlled pre-signed URL for playback
- S3 key format: `media/{teacher_id}/{grade_id}/{uuid}.webm` — no student PII in any key
- Locked grades suppress the record button (read-only when `grade.is_locked`)
- MIME type validation server-side; 50 MB size cap; graceful degradation on permission denial

**Shipped (M4.11 — video comments):**
- In-browser webcam + microphone recording via MediaRecorder API (`VideoRecorder` component in `EssayReviewPanel`)
- Optional screen share mode: `getDisplayMedia` captures display video, combined with microphone audio from `getUserMedia`
- Records as `video/webm`; same 3-minute limit, same S3 upload and API flow as M4.10
- Live webcam preview while recording; post-recording video preview before saving
- Graceful degradation: `NotAllowedError` on camera denied → audio-only fallback offered; both camera and mic denied → combined error; screen share denied → screen-share-specific error; hardware errors (`NotFoundError`, `NotReadableError`) shown separately
- Video comments filter by `mime_type.startsWith("video/")` in the shared `media-comments` query

**Shipped (M4.12 — media comment bank and export):**
- `is_banked` boolean column on `media_comments` (migration `019_media_comment_add_is_banked`)
- `POST /media-comments/{id}/save-to-bank` — marks a recorded comment as reusable; sets `is_banked=true`
- `GET /media-comments/bank` — lists all banked (reusable) comments for the teacher, newest first
- `POST /grades/{id}/media-comments` extended: accepts optional `source_id` form field; when provided, copies the banked comment's S3 object to a new key scoped to the target grade and creates a new `MediaComment` row (no re-recording needed)
- `MediaBankPicker` component in `EssayReviewPanel` — toggle-to-open bank picker listing saved comments with duration, type label, and per-item Apply button; disabled on locked grades
- "Save to bank" button on each `AudioRecorder` comment row — marks the comment as banked and invalidates the bank query cache
- Pre-signed playback URLs remain scoped to the owning teacher; expire per `S3_PRESIGNED_URL_EXPIRE_SECONDS`
- PDF export (M3.24) updated: each student PDF includes a "Media Comments" section listing the comment IDs with instructions to retrieve playback URLs via `GET /media-comments/{id}/url`

**Pending:**
- Auto-transcription for accessibility

---

## Purpose

Allow teachers to attach voice or video comments to student essays as an alternative or supplement to written feedback. For writing instruction specifically, hearing a teacher's tone, emphasis, and reasoning is often more impactful than reading a typed note. It also saves time — a 90-second voice comment frequently conveys more than five minutes of typing.

---

## User Story

> As a teacher, I want to record a short voice or video comment on a student's essay, so I can deliver richer, more personal feedback without spending more time than writing it out.

---

## Key Capabilities

### Voice Comment Recording
- Record a short audio comment (up to 3 minutes) directly in the review interface
- Attach to the overall essay or to a specific criterion
- Playback in the interface before saving — re-record if needed
- No external app or file upload required — recorded in-browser

### Video Comment Recording
- Record a short webcam or screen + webcam video comment (up to 3 minutes)
- Same attachment model as voice: overall or criterion-level
- Screen recording option: teacher can annotate or scroll through the essay while narrating

### Attachment to Exported Feedback
- Audio and video comments are included when feedback is exported or shared
- PDF export includes a link or QR code to the media file
- Media files are stored securely and access-controlled — only accessible to the intended student (when sharing is enabled)

### Teacher Efficiency
- Pre-recorded common comments can be saved to a media comment bank
- Example: a standard 60-second explanation of what "weak evidence integration" looks like, reusable across students with the same gap
- Saves time on recurring issues without losing the personal quality of voice feedback

---

## Acceptance Criteria

- A teacher can record and attach a voice comment to an essay without leaving the review interface
- Recorded media is playable immediately after recording with no processing delay
- Media comments are preserved in the export and accessible to the student when feedback is shared
- A saved media comment from the comment bank can be applied to a new essay in a single action

---

## Edge Cases & Risks

- Browser microphone/camera permissions — must degrade gracefully if permissions are denied, with a clear prompt to enable them
- Storage costs for audio and video at scale — need a per-file size limit and a retention policy
- Accidental recordings that capture background noise or personal information — teacher must be able to delete and re-record before sharing
- Accessibility: audio-only feedback is inaccessible to students with hearing impairments — auto-transcription of voice comments should be considered

---

## Open Questions

- Is media feedback a Phase 2 feature or can it be deferred to Phase 3 without competitive risk?
- Do we auto-transcribe voice comments for accessibility and searchability?
- Should media comments be part of the standard export or only available via the in-app sharing flow?
