# Feature: Teacher Worklist

**Phase:** 4 — Prioritization
**Status:** Planned

---

## Purpose

Surface the most important actions a teacher should take right now — not a dashboard to explore, but a ranked list of things to do. This is the system's answer to the question every teacher has on Monday morning: "Where do I start?" It applies the prioritization logic from student profiles and class insights and converts it into clear, actionable next steps.

---

## User Story

> As a teacher, I want to see a prioritized list of who needs my attention and what I should do, so I can make the most of the time I have without having to figure it out myself.

---

## Key Capabilities

### Ranked Student Queue
- Ordered list of students by urgency of need
- Each entry shows: student name, reason for prioritization, suggested action
- Reasons include: persistent skill gap, recent regression, at-risk trajectory, no improvement after resubmission

### Priority Signals
- Persistent gap: student has been in the same skill group for 2+ assignments
- Regression: student's score dropped significantly from last assignment
- High inconsistency: scores vary widely across assignments, suggesting unstable skill
- Non-responders: student received feedback but showed no improvement on resubmission

### Suggested Actions Per Student
- Linked directly to specific next steps: "Schedule a 1:1 check-in", "Assign targeted exercise on thesis writing", "Review their last 3 essays together"
- Actions are generated from the Instruction Engine based on the student's gap profile
- Teacher can mark an action as done, snooze it, or replace it

### Worklist Filters
- Filter by: action type, skill gap, urgency level, student group
- Default view: top 5–10 highest-priority students
- Expand to see full class if needed

### Completion Tracking
- Mark items complete or in progress
- Completed actions are logged and shown in the student's profile history
- Worklist refreshes after each new assignment is graded

---

## Acceptance Criteria

- The worklist is generated automatically after each graded assignment with no teacher configuration required
- Each worklist item includes a student name, the reason they are prioritized, and at least one suggested action
- A teacher can mark a worklist item as complete and that action is logged in the student's profile
- The worklist defaults to showing no more than 10 items — the most urgent ones — with an option to expand

---

## Edge Cases & Risks

- If every student has a gap, the worklist is not useful — prioritization requires genuine triage, not just listing everyone
- Teachers may disagree with the system's prioritization — must support override and manual reordering
- Action suggestions must be concrete and achievable within the teacher's actual constraints (class time, resources) — vague suggestions destroy trust

---

## Open Questions

- Does the worklist persist across sessions, or is it regenerated fresh after each assignment?
- Should the system learn which types of actions a teacher follows through on and weight those higher?
- Is there a student-facing version — a "what should I work on" list for the student themselves?
