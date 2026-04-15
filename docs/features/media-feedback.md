# Feature: Media Feedback

**Phase:** 2 — Workflow
**Status:** Planned

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
