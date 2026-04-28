# M5 Student Intelligence — Business Release Notes

**Release**: v0.6.0  
**Milestone**: M5 — Student Intelligence  
**Date**: April 2026  
**PRs**: #168–#179 (12 pull requests)

---

## What's New for Teachers

### Student skill profiles

Every time you lock a grade, the system now builds a persistent skill profile for that student. Rubric criteria are automatically mapped to six canonical skill dimensions — thesis, evidence, organization, analysis, mechanics, and voice — so you can compare growth across assignments even when you change rubrics.

Open any student from the class roster to see their full profile: a skill bar chart showing where they currently stand, a timeline of every graded assignment with per-criterion scores, and callout cards for their strengths and the areas that need attention most. A growth indicator on each skill tells you at a glance whether the student is improving, declining, or holding steady.

You can also add private teacher notes to any student profile — these are visible only to you and never shared with students.

### Class skills heatmap

The assignment page now includes a class heatmap: a grid with every student as a row and every skill dimension as a column, color-coded from low to high. Sort by any skill to see immediately which students are underperforming in that area. Click any cell to go directly to that student's profile.

This is the fastest way to answer questions like "who in my class is struggling with evidence?" or "is my feedback on organization landing?"

### Class insights panel

Alongside the heatmap, a new insights panel shows:

- **Common issues** — the feedback phrases that appeared most often across graded essays, ranked by frequency with student counts. Helps you identify topics that need a whole-class lesson rather than individual intervention.
- **Score distribution** — a histogram per criterion so you can see whether your class is clustered, spread out, or bimodal.
- **Cross-assignment trends** — how class averages on each skill have moved across your last several assignments.

### Writing process visibility

For essays submitted using the new in-browser writing interface, you can now see how the essay was written — not just what was submitted. The writing process panel in the essay review interface shows:

- A session timeline (when the student worked on the essay, with duration per session)
- Flags for large paste events (content that appeared suddenly rather than being typed)
- A snapshot viewer that lets you read the essay at any saved point in its history
- A process callout summarizing key signals (e.g., "Written in a single 20-minute session with no prior drafts")

This information is there to inform your professional judgment — not to make conclusions for you. A student writing their essay in one focused session may simply be a confident writer.

### In-browser essay writing (student submission)

Students can now write and submit essays directly inside the assignment page — no upload required. The writing interface auto-saves every 10 seconds so no work is lost. Teachers see the submitted text in the review panel exactly as written. This is the foundation that makes writing process visibility possible.

---

## What Didn't Change

- **Human-in-the-loop guarantee** — skill profiles, heatmaps, and insights are read-only views for teacher use. No grade, assignment, or feedback is modified automatically. All of M5's outputs are observational.
- **Existing grades and rubrics** — M5 is fully additive. All previously locked grades, rubrics, assignments, and student records are unaffected. Skill profiles are built forward from grades locked after the M5 update.
- **Student-facing interface** — there is no student-facing view. Skill profiles, notes, and insights are visible only to the teacher.

---

## What's Next (M6 — Prioritization & Instruction)

M6 uses the skill profiles built in M5 to drive action. Auto-grouping will cluster students by shared skill gaps so you can run targeted small-group work. A teacher worklist will surface the students who need your attention most — persistent gaps, score regressions, non-responders — ranked by urgency and each paired with a suggested action. The instruction engine will generate mini-lessons, exercises, and intervention suggestions grounded in your actual class data.
