# Feature: Instruction Engine

**Phase:** 5 — Instruction
**Status:** Planned

---

## Purpose

Convert skill gap diagnoses into concrete instructional actions. The diagnosis is worthless if the teacher doesn't know what to do with it. The instruction engine closes the loop between knowing a student struggles with evidence integration and actually doing something about it — by recommending specific, ready-to-use teaching activities.

---

## User Story

> As a teacher, I want the system to recommend specific exercises, mini-lessons, and interventions based on what each student or group needs, so I can take action without spending time searching for or creating materials.

---

## Key Capabilities

### Mini-Lesson Recommendations
- Recommend a 10–15 minute classroom activity targeting a specific skill gap
- Each recommendation includes: objective, suggested structure, example or model text
- Tied to the gap identified in student profiles or the class worklist

### Targeted Exercise Assignment
- Recommend a focused writing exercise for a specific student or group
- Exercises target a single rubric dimension: e.g., "Write a paragraph where the evidence directly supports the claim"
- Teacher reviews the recommendation, edits if needed, and assigns explicitly — the exercise only appears in the student's record after teacher confirmation

### Practice Prompt Generation
- Generate a short writing prompt designed to exercise a specific skill
- Prompts are contextually appropriate for grade level and subject
- Teacher can edit before assigning

### Intervention Recommendations
- For students with persistent or severe gaps, suggest more intensive interventions: 1:1 conferences, reading scaffolds, peer review pairings
- Differentiate between group instruction (same gap in many students) and individual intervention (isolated case)

### Recommendation Confidence
- Each recommendation includes the evidence behind it: which assignments, which skills, which patterns triggered the suggestion
- Teacher can accept, modify, or dismiss any recommendation

---

## Acceptance Criteria

- For any skill gap identified in the student profile or worklist, the system can produce at least one concrete instructional recommendation
- A mini-lesson recommendation includes a clear objective, a suggested structure, and an example
- A teacher can assign a targeted exercise to a student or group in a single action
- Recommendations reference the specific student data that triggered them — not generic advice

---

## Edge Cases & Risks

- Recommendations that are too vague ("practice writing more") destroy teacher trust immediately — every recommendation must be specific and immediately actionable
- Recommendations for skills that require prerequisite knowledge the student lacks — the system must not suggest advanced practice before foundational gaps are addressed
- Grade-level appropriateness: a mini-lesson for a 7th grader needs to differ from one for an 11th grader — recommendations must be level-aware

---

## Open Questions

- Do we build a library of exercises and mini-lessons, or generate them dynamically with AI?
- Should teachers be able to contribute their own exercises to a shared recommendation pool?
- Does the system track whether a recommendation was followed and whether it improved outcomes?
