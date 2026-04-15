# Feature: Batch Grading

**Phase:** 1 — MVP
**Status:** Planned

---

## Purpose

Allow teachers to grade an entire class set of essays in a single operation rather than one at a time. Batch grading is what converts the AI engine from a convenience tool into a time-saving system — the value compounds when a teacher submits 30 essays and gets back 30 graded drafts ready to review.

---

## User Story

> As a teacher, I want to submit all essays for an assignment at once and have the AI grade them in the background, so I can review results instead of waiting for each one individually.

---

## Key Capabilities

### Bulk Submission
- Upload multiple files at once (ZIP, drag-and-drop folder, or multi-file select)
- CSV import: student name + essay text as columns
- Auto-associate each essay with a student record in the class roster

### Queue Processing
- Essays enter a processing queue after submission
- Each essay is graded independently and asynchronously
- Teacher can close the browser and return — results persist

### Progress Tracking
- Real-time progress indicator: "12 of 30 graded"
- Per-essay status: queued, processing, complete, failed
- Failed essays are flagged with an error reason and can be retried individually

### Partial Results
- Completed essays are available for review as soon as they finish — teacher doesn't wait for the full batch
- Results appear in the review queue in real time

### Prioritization of Queue
- Teacher can manually move an essay to the front of the queue
- High-confidence essays are processed in the same pass; flagged essays are surfaced for review first

---

## Acceptance Criteria

- A teacher can upload 30 essays and have all of them graded within 5 minutes
- Each essay in the batch is associated with the correct student record
- If one essay fails, the rest of the batch continues processing
- Partial results are available for review before the full batch completes
- The teacher receives a notification (in-app) when the batch is complete

---

## Edge Cases & Risks

- Duplicate submissions (same student submits twice) — system should detect and prompt teacher to choose the correct version
- Essays uploaded without student names — teacher must be able to assign them to students manually before grading is finalized
- Large batches (100+ essays for college instructors) — processing time and cost must be considered; may need queuing or rate limiting

---

## Open Questions

- Do we support batch re-grading (re-run AI on all essays in an assignment after rubric changes)?
- Should teachers be able to pause or cancel a batch mid-processing?
- What is the upper limit on batch size for MVP, and how does that change in later phases?
