# Feature: Auto-Grouping

**Phase:** 4 — Prioritization
**Status:** Planned

---

## Purpose

Automatically organize students into instructional groups based on shared skill gaps. Teachers routinely need to differentiate instruction — but identifying who shares the same weakness, across 30 student profiles, is manual and time-consuming. Auto-grouping makes differentiation the default, not the exception.

---

## User Story

> As a teacher, I want the system to automatically group students by their shared writing weaknesses, so I can plan differentiated instruction without analyzing each student's data manually.

---

## Key Capabilities

### Gap-Based Grouping
- Cluster students who share the same underperforming rubric dimension(s)
- Groups are generated automatically after each assignment is graded
- Each group is labeled by the shared gap: e.g., "Weak Evidence Integration (8 students)"

### Group Types
- Single-skill groups: students weak in one specific area
- Multi-skill groups: students with overlapping gaps across two or more dimensions
- Growth groups: students who showed recent improvement on a skill and are ready for extension

### Group Visualization
- Simple list view: group name, number of students, affected skill(s)
- Expand to see the individual students and their scores
- Cross-reference with class heatmap

### Group Actions
- Assign a mini-lesson or targeted exercise to the whole group (feeds into Instruction Engine)
- Export group list for use in LMS or offline planning
- Manually adjust groups — add or remove students as needed

### Group Stability Over Time
- Track whether students move between groups across assignments
- Flag students who are persistently in the same gap group (intervention signal)
- Celebrate when a student exits a gap group (growth signal)

---

## Acceptance Criteria

- Groups are generated automatically after each batch grading is complete, requiring no teacher action
- Each group is labeled with a plain-language description of the shared skill gap
- A teacher can view all groups for a class in a single screen without needing to configure anything
- Groups can be manually edited without affecting the underlying student profile data

---

## Edge Cases & Risks

- Students with multiple overlapping gaps may appear in several groups — avoid overwhelming the teacher with too many groups; surface the top 3–5 most actionable ones
- Classes with very few students may produce groups of 1–2, which are less useful — set a minimum group size threshold or surface singletons differently
- Groups must update when a teacher overrides scores, not just after AI grading

---

## Open Questions

- Should the system suggest a teaching action for each group automatically, or wait for the teacher to request one?
- How do we name groups in a way that is useful and not stigmatizing?
- Should groups be visible to other teachers who share a student (e.g., a reading specialist)?
