# Feature: Rubric Builder

**Phase:** 1 — MVP
**Status:** Planned

---

## Purpose

Give teachers a tool to define, save, and reuse grading rubrics that drive the AI evaluation engine. The rubric is the contract between the teacher's intent and the AI's output — it must be expressive enough to capture real pedagogical standards while remaining simple enough to build in minutes.

---

## User Story

> As a teacher, I want to create a rubric that reflects my grading criteria, so the AI evaluates student writing the way I would.

---

## Key Capabilities

### Criterion Management
- Add, edit, reorder, and delete criteria (e.g., Thesis, Evidence, Organization, Voice)
- Each criterion has: name, description, and scoring scale
- Optional: anchor descriptions per score level (what a "3" looks like vs a "5")

### Scoring Scales
- Support multiple scale types: 1–4, 1–5, 1–10, percentage
- Per-criterion weight (e.g., Thesis = 30%, Evidence = 40%, Organization = 30%)
- Auto-calculate weighted total grade

### Rubric Templates
- System-provided starter templates (e.g., 5-paragraph essay, argumentative essay, research paper)
- Teachers can save their own rubrics as templates
- Templates are reusable across assignments and classes

### Rubric Versioning
- Track changes to a rubric over time
- Warn teacher if a rubric is edited after grading has begun on an assignment
- Preserve original rubric snapshot with each graded assignment for audit purposes

---

## Acceptance Criteria

- A teacher can create a rubric with 3–8 criteria in under 5 minutes
- Weights across all criteria must sum to 100% before a rubric can be used — the UI enforces this
- A saved rubric can be applied to a new assignment without re-entering any criteria
- Editing a rubric mid-assignment triggers a warning and requires explicit confirmation

---

## Edge Cases & Risks

- Teachers who import rubrics from PDFs or Word docs — we may need a rubric import parser in a later phase
- Criterion descriptions that are vague or too short may produce inconsistent AI scoring — consider a quality hint or warning
- Anchor descriptions (score-level exemplars) significantly improve AI grading consistency but add authoring time — make them optional but encourage them

---

## Open Questions

- Should rubrics be shareable between teachers at the same school?
- Do we support holistic rubrics (single overall score) in addition to analytic rubrics (per-criterion)?
- Should the system suggest rubric improvements based on grading inconsistency over time?
