# Feature: Resubmission Loop

**Phase:** 5 — Instruction
**Status:** Planned

---

## Purpose

Enable students to revise their work and track whether instruction actually led to improvement. Resubmission closes the most important gap in traditional grading: feedback is given, but no one ever checks if the student applied it. The resubmission loop makes improvement visible — to the student, the teacher, and the system.

---

## User Story

> As a teacher, I want students to be able to revise their essays and resubmit, so I can see whether my feedback had an impact and the system can track improvement over time.

---

## Key Capabilities

### Resubmission Intake
- Teacher enables resubmission on a per-assignment basis
- Student (or teacher on their behalf) submits a revised essay against the same assignment
- Both the original and revised version are stored and linked

### Automated Version Comparison
- Side-by-side view of original and revised essay
- Highlight what changed between versions
- Re-run AI grading on the revision against the same rubric

### Improvement Tracking
- Show score delta per criterion: original vs. revised
- Highlight which specific feedback points the student addressed
- Flag cases where revision shows no meaningful change despite having received feedback

### Feedback Addressed Detection
- Identify whether the student's revision responds to the feedback given
- Example: if feedback noted weak evidence, did the revision add or improve evidence?
- This is a strong signal for both student growth and feedback quality

### Iteration History
- Support multiple rounds of revision (v1, v2, v3)
- Full history is visible in the student profile
- Growth across iterations contributes to the longitudinal skill trend

---

## Acceptance Criteria

- A teacher can enable resubmission for an assignment and the student can submit a revised essay linked to the original
- The system produces a comparison showing score changes per criterion between the original and revised submission
- Improvement in the revision is reflected in the student's skill profile
- If no rubric-relevant changes were made, the system flags the revision as low-effort rather than re-scoring it as improved

---

## Edge Cases & Risks

- Students who copy feedback verbatim into their essay rather than genuinely revising — the system should detect surface-level changes that don't reflect real improvement
- Revisions that change the topic entirely — the system must verify the revision is still responding to the original assignment prompt
- Teachers who allow unlimited resubmissions may create grading burden — consider setting a resubmission limit per assignment

---

## Open Questions

- Should the revised grade replace the original grade, average with it, or be tracked separately?
- Do students see the score comparison, or only the teacher?
- Should the system alert the teacher when a revision has been submitted and is ready to review?
