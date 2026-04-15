# Feature: AI Grading Engine

**Phase:** 1 — MVP
**Status:** Planned

---

## Purpose

Produce consistent, rubric-grounded scores for student essays. This is the core technical capability of the product — everything else depends on the quality and reliability of the grading output. The engine must be accurate enough to trust, transparent enough to audit, and fast enough to use at scale.

---

## User Story

> As a teacher, I want the AI to score each essay against my rubric criteria, so I can review results instead of grading from scratch.

---

## Key Capabilities

### Per-Criterion Scoring
- Score each rubric criterion independently
- Return a numeric score within the rubric's defined scale
- Generate a justification for each score, grounded in specific text from the essay

### Overall Grade Calculation
- Apply criterion weights to compute a weighted total score
- Display both raw scores per criterion and the final weighted grade
- Surface the calculation so teachers can verify it

### Configurable Strictness
- Teacher-adjustable grading posture: lenient, balanced, or strict
- Affects how borderline cases are resolved, not what the rubric says
- Visible setting per assignment so results are reproducible

### Evidence Grounding
- Each score justification must cite or reference specific passages in the student's essay
- No score should be given without a rationale tied to actual content
- AI must not penalize students for content the rubric doesn't assess

### Consistency Model
- Multiple essays graded against the same rubric should be scored consistently
- The engine must not drift in interpretation across a batch

---

## Acceptance Criteria

- Each graded essay returns a score for every criterion defined in the rubric
- Every criterion score includes a written justification of 1–3 sentences citing the essay
- The weighted total grade is calculated correctly and matches manual calculation
- Grading a 500-word essay completes in under 10 seconds
- Two essays of similar quality receive scores within one point of each other on a 1–5 scale

---

## Edge Cases & Risks

- Off-topic essays (student wrote about the wrong subject) — engine should flag, not silently score low
- Extremely short essays (under 100 words) — may lack enough content to assess some criteria
- AI-generated student writing — detection is a separate concern, but the grading engine should not be influenced by stylistic polish that doesn't reflect rubric criteria
- Prompt injection risk: essay content must not be able to influence grading instructions — system prompt and rubric must be protected from essay input

---

## Open Questions

- How do we measure and track grading accuracy over time? Do we build a ground-truth dataset?
- Should teachers be able to calibrate the engine by providing sample scored essays?
- What model(s) do we use, and how do we handle model version changes that could shift grading behavior?
- Do we expose confidence scores per criterion at this phase or defer to the Confidence Scoring feature?
