# Feature: Student Profiles

**Phase:** 3 — Insights
**Status:** Planned

---

## Purpose

Build a persistent, longitudinal view of each student's writing ability. Rather than treating every essay as a standalone event, the system accumulates evidence over time to show where each student is, where they've been, and where they're headed. This is the foundation for every prioritization and instruction feature that follows.

---

## User Story

> As a teacher, I want to see how each student is performing across all their writing assignments — not just the most recent one — so I can understand their real skill level and how they're developing over time.

---

## Key Capabilities

### Skill Breakdown
- Per-student breakdown of performance by rubric dimension (e.g., Thesis, Evidence, Organization)
- Aggregated across all assignments, weighted by recency
- Displayed as a simple skill radar or bar chart — not a wall of numbers

### Historical Timeline
- Chronological view of all assignments: score, rubric used, date
- Drill down into any past assignment to see the original essay, scores, and feedback
- Trend line per skill dimension showing improvement or regression

### Strengths and Gaps
- Auto-identified: consistently strong areas and consistently weak areas
- Based on score patterns, not a single data point
- Framed as actionable insight: "Needs consistent support with evidence integration"

### Growth Tracking
- Highlight when a student improves meaningfully on a previously weak skill
- Flag when a previously strong skill shows signs of regression
- Show net change over a configurable time window (last 30 days, last semester, all time)

### Teacher Notes
- Private notes field per student — not shared with the student
- Notes persist across assignments and are visible in the worklist feature

---

## Acceptance Criteria

- A teacher can view a student's skill profile after at least 2 graded assignments
- The profile shows per-skill scores aggregated across all assignments, with a trend indicator for each
- Clicking any assignment in the history opens the original graded essay
- Strengths and gaps are automatically identified and displayed without teacher configuration

---

## Edge Cases & Risks

- A student who switches classes mid-year — profiles should persist and be transferable
- Rubric dimensions vary by assignment — profiles must normalize across different rubric structures intelligently
- Small data problem: a student with only one submission doesn't have enough history for trends — display data without false trend lines

---

## Open Questions

- Do students have access to their own profile? If so, what do they see?
- How do we handle rubric schema differences across assignments when aggregating skill scores?
- Should profiles be visible to school administrators or only to the assigned teacher?
