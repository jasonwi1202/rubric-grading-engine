# Feature: Regrade Requests

**Phase:** 2 — Workflow
**Status:** Planned

---

## Purpose

Give students a structured, asynchronous way to dispute a grade — and give teachers a way to handle those disputes without email threads or office hours. Without this, teachers who share AI-generated grades will get ad hoc challenges with no process to manage them. A clear regrade workflow also signals to students that the system is fair and the teacher remains in control.

---

## User Story

> As a teacher, I want a structured way to log and manage grade disputes from students, so I can review them efficiently in one place rather than through email threads or in-class conversations.

---

## Key Capabilities

### Regrade Request Logging
- Teacher logs a regrade request on behalf of a student (verbal, email, or in-class dispute)
- Required fields: which criterion is being disputed and the student's stated justification
- Optional: teacher note with their initial assessment of the dispute
- Alternatively: teacher shares a lightweight form link with the student — no student account required, just a name, criterion, and written justification — which the teacher then reviews before it enters the queue
- Submission window is configurable by the teacher (e.g., within 7 days of grade release)

### Teacher Regrade Review Queue
- All pending regrade requests appear in a dedicated queue, separate from the main grading flow
- Each request shows: student name, disputed criterion, original score, student justification
- Teacher can view the original essay, original AI score, and any prior edits side by side

### Resolution Actions
- **Approve:** adjust the score (teacher sets the new value), notify student
- **Deny:** decline with a written explanation, notify student
- **Partial approval:** adjust some criteria but not others
- All resolutions are logged in the audit trail

### Request Limits
- Teacher sets the maximum number of regrade requests per student per assignment
- Prevents abuse while still allowing legitimate disputes

### Outcome Tracking
- Track regrade outcomes over time: how often requests are approved vs. denied
- If a teacher approves a high percentage of requests on a specific criterion, that may signal a calibration issue in the AI grading or rubric — surface this as an insight

---

## Acceptance Criteria

- A teacher can view all pending regrade requests for an assignment in a single queue
- Each request includes the student's justification and links directly to the original graded essay
- Resolving a request (approve or deny) updates the grade and logs the outcome in under 3 clicks
- The teacher can close the regrade window for an assignment, after which no new requests are logged
- Resolution notes are exportable for the teacher's own records or for escalation documentation

---

## Edge Cases & Risks

- Disputes logged without substantive justification ("I worked hard on this") — the required justification field helps, but the teacher still bears the burden of responding
- A regrade approval that changes a score may affect class analytics and student profile data — all downstream data must update when a grade changes
- Students who escalate to parents or administrators when denied — the audit trail and written denial reason are the teacher's protection here

---

## Open Questions

- Should the lightweight shared form (no student account) be the default dispute path, or teacher-logged entry?
- Should regrade requests be available from day one (Phase 1) given that teachers sharing grades will face disputes immediately?
- Should the system flag when a regrade approval rate on a specific criterion exceeds a threshold, suggesting a systemic grading issue?
