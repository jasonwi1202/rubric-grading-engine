# Feature: Feedback Generator

**Phase:** 1 — MVP
**Status:** Planned

---

## Purpose

Produce written feedback that is specific, actionable, and grounded in the student's actual writing. Feedback is the primary student-facing output of the system — it must feel like it came from someone who read the essay, not a generic scoring rubric.

---

## User Story

> As a teacher, I want the AI to generate clear, specific feedback for each student, so I can share it directly or use it as a starting point without writing from scratch.

---

## Key Capabilities

### Summary Feedback
- One overall paragraph summarizing strengths and areas for improvement
- Tone-adjusted based on teacher preference (see Tone Options below)
- References the student's actual writing — no generic statements

### Criterion-Specific Feedback
- A short feedback note for each rubric criterion
- Tied to the score given — explains what earned that score and what would improve it
- Written from the teacher's perspective, not as an AI explanation

### Inline Suggestions (Optional)
- Highlight specific sentences or passages in the essay
- Attach a short comment to each highlight
- Mode: additive only — highlights show where feedback applies, not rewrites

### Tone Options
- **Encouraging:** lead with strengths, frame improvements as growth opportunities
- **Direct:** clear, concise, no softening — appropriate for older or higher-level students
- **Academic:** formal register, discipline-specific language
- Teacher sets the default tone per class or per assignment

### Comment Bank Integration
- Save any generated feedback snippet to a reusable comment bank
- Suggest saved comments when similar issues appear in future essays
- Teacher can edit before applying

---

## Acceptance Criteria

- Every graded essay has a summary feedback paragraph and at least one feedback note per criterion
- Feedback never includes generic statements that could apply to any essay (e.g., "Good job!" without specifics)
- Teacher can change the tone setting and regenerate feedback for a single essay without re-grading
- A teacher can edit any feedback field inline before sharing with the student

---

## Edge Cases & Risks

- Very low-scoring essays may have little positive to say — feedback must still be constructive, not discouraging
- Essays with strong surface writing but weak argument may receive positive-sounding feedback that misleads the student — criterion specificity must prevent this
- Feedback length needs guardrails — too short is unhelpful, too long won't be read

---

## Open Questions

- Should students ever see raw AI feedback, or does it always go through teacher review first?
- Do we support per-student tone override (e.g., a student who needs extra encouragement)?
- Should the system learn over time which feedback comments a teacher tends to edit or reject?
