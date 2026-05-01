# M6 Prioritization & Instruction — Business Release Notes

**Release**: v0.7.0  
**Milestone**: M6 — Prioritization & Instruction  
**Date**: April 2026  
**PRs**: #197–#212 (16 pull requests)

---

## What's New for Teachers

### Automatic skill-gap groups

After each grading batch, the system now automatically clusters your students into small groups based on shared underperforming skill dimensions. You didn't set up groups — the AI did, based on the locked grades and skill profiles already in the system.

Open any class and switch to the **Groups** tab. Each group shows:

- The skill gap that defines the group (e.g., "Evidence", "Organization")
- The students in the group with their current skill scores
- A stability indicator: **New** (appeared this assignment), **Persistent** (same gap for 2+ assignments), or **Exited** (gap has closed)

You can manually adjust any group — add or remove a student — and the change is saved immediately.

Persistent groups are the most actionable signal: these are students who have had the same weakness flagged multiple times and haven't improved yet.

### Teacher worklist

A new **Worklist** page gives you a ranked, prioritized list of students that need attention — computed automatically from skill profiles and group membership.

Each item on the list shows:

- The student and their trigger condition (persistent gap, score regression, no improvement after a resubmission, high inconsistency across criteria)
- The skill dimension at issue
- A suggested action (e.g., "Generate instruction recommendation", "Offer resubmission")
- Urgency level so you can work top-to-bottom

You can **mark an item done**, **snooze it** (it reappears at your next grading cycle), or **dismiss it** permanently. The worklist filters by action type, skill, and urgency level, and shows the top 10 by default with a "Show all" option.

This is not a to-do list the system manages for you — it's a reading list your professional judgment drives. Nothing happens to a student record until you take an explicit action.

### AI instruction recommendations

From any worklist item or student profile gap, you can now request AI-generated instruction recommendations tailored to that student's specific skill weaknesses.

Each recommendation card shows:

- The targeted skill dimension and what the evidence says about the gap
- A recommended mini-lesson, targeted exercise, or intervention strategy
- Estimated time (in minutes)
- Strategy type (guided practice, independent practice, or direct instruction)

You review every recommendation before anything happens. To act on it, you use the **Assign exercise** button — an explicit confirmation step. Dismissed recommendations are logged but never applied.

Group recommendations work the same way: select a group and request a recommendation for the shared skill gap. The evidence summary references all students in the group collectively.

### Resubmission loop

You can now accept revised essays from students and grade them as new versions — without losing the original submission.

- The **Resubmit** button appears on any graded essay (configurable per-assignment limit on number of resubmissions)
- The revised essay is graded automatically, just like the original
- A **side-by-side diff view** shows the original and revised text with score deltas per criterion
- Feedback-addressed indicators show which specific feedback points the revision responded to
- A flag appears when a revision looks low-effort (surface-level changes without substantive improvement)
- The student's profile reflects the improvement (or lack of it) from the resubmission

The version history tab on any essay lets you browse all submitted versions.

---

## What Didn't Change

- **Human-in-the-loop guarantee** — auto-grouping, the worklist, and instruction recommendations are read-only suggestions. No grade is changed, no assignment is made, and no feedback is sent to any student without your explicit confirmation.
- **No student-facing interface** — groups, worklist items, and recommendations are visible only to the teacher. Students see nothing different until you choose to act.
- **Existing grades and rubrics** — M6 is fully additive. All prior assignments, grades, skill profiles, and student records are unaffected.

---

## What's Next (M7 — Closed Loop)

M7 brings automation agents that proactively scan for intervention signals on a schedule, predictive trajectory risk detection (students declining across multiple assignments), and a conversational teacher copilot for querying your class data in plain language.

---

## Security & Compliance Updates

M6 also includes a SOC 2 / FERPA hardening sweep (PR #214) with no visible impact on the teacher workflow:

- Student data is no longer exposed in any server error messages or log output
- Invalid session tokens now correctly trigger a silent re-authentication so teachers are not unexpectedly logged out
- Referential integrity is now fully enforced at the database level for all audit records
- A new automated test proves that the database refuses to show one teacher's data to another teacher at the database layer, independent of application code
