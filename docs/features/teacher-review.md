# Feature: Teacher Review & Control

**Phase:** 1 — MVP
**Status:** Planned

---

## Purpose

Give teachers full authority over every score and piece of feedback before it reaches students. AI grading is a first pass — the teacher is the decision-maker. This feature is what makes the system trustworthy: it never hides the AI's work and never removes the teacher from the loop.

---

## User Story

> As a teacher, I want to review, edit, and finalize AI-generated grades and feedback before they are shared with students, so I remain in control of what my students receive.

---

## Key Capabilities

### Score Override
- Edit any criterion score directly in the review interface
- Override is logged with a timestamp — distinguishable from the original AI score
- Weighted total recalculates automatically when a criterion score is changed

### Feedback Editing
- Edit any feedback text inline — summary or criterion-level
- Changes are tracked: show AI original vs. teacher-edited version on request
- Rich text editing: bold, bullet points, paragraph breaks

### Accept / Reject AI Suggestions
- For inline suggestions and highlighted passages, teacher can accept or dismiss each one individually
- Bulk accept all / reject all option for speed

### Grade Lock
- Teacher explicitly locks a grade to mark it final
- Locked grades cannot be changed by the AI on re-run
- Locked status is visible in the assignment queue

### Edit History & Audit Log
- Every change to a score or feedback field is logged
- Shows: original AI value, teacher edit, timestamp
- Supports accountability and auditability requirements for schools

### Review Queue
- List view of all submitted essays with status: unreviewed, in-progress, reviewed, locked
- Sort and filter by status, student name, score range, or confidence level
- Keyboard shortcuts for fast navigation between essays

---

## Acceptance Criteria

- A teacher can override any score and the total recalculates in under 1 second
- Every score override is visible in the audit log with the original AI value preserved
- A teacher can navigate between essays, edit scores and feedback, and lock a grade without leaving the review interface
- Locked grades are clearly distinguished from unlocked grades in all views

---

## Edge Cases & Risks

- Teacher edits a score but forgets to lock — system should prompt before the assignment is marked complete
- Multiple teachers reviewing the same class (co-teachers) — need to handle concurrent edits and show who made a change
- Teacher wants to re-run AI grading after editing the rubric — locked essays should be excluded by default

---

## Open Questions

- Should teachers be able to add a private note to an essay (not shared with the student)?
- Do we surface a "confidence" indicator to help teachers prioritize which essays to review most carefully?
- Should the system learn from teacher overrides to improve future AI scoring?
