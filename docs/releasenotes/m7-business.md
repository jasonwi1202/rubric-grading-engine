# M7 Closed Loop — Business Release Notes

**Release**: v0.8.0  
**Milestone**: M7 — Closed Loop  
**Date**: May 2026  
**PRs**: #221–#224 (feature delivery), #225 (release finalization)

---

## What's New for Teachers

### Intervention recommendations

The platform now proactively scans student skill profiles in the background and surfaces **intervention recommendations** for students who need additional support.

Each recommendation explains:

- why the intervention was triggered
- the supporting evidence (trend, average score, assignment count)
- the suggested next action

You decide what happens next. A recommendation stays in **pending review** until you either approve it or dismiss it. Nothing is assigned or changed automatically.

### Predictive trajectory risk

The worklist can now surface **predictive risk signals** before a student has a confirmed regression.

These items flag patterns like repeated score declines across recent assignments and include:

- a predictive label
- a confidence indicator
- the recent trend data that triggered the signal

This gives teachers an earlier warning window to intervene before the next graded essay confirms the decline.

### Teacher copilot

Teachers can now open a dedicated **Copilot** panel and ask plain-language questions about class data, such as:

- Who is falling behind on thesis development?
- What should I teach tomorrow?
- Which students have not improved since my last feedback?

The copilot returns structured, explainable answers and can link you directly to relevant student profiles.

The copilot is intentionally **read-only**:

- it does not change grades
- it does not assign work
- it does not trigger interventions automatically

It surfaces information for teacher review only.

### Demo coverage for M7

The local demo stack now includes seeded M7 data so the release can be demonstrated end to end:

- predictive worklist data
- intervention recommendation data
- a working teacher copilot experience using deterministic fake-LLM responses

No external OpenAI key is required for the demo.

---

## What Didn't Change

- **Human-in-the-loop remains mandatory** — all intervention and copilot flows remain advisory until the teacher explicitly chooses an action elsewhere in the product.
- **No student-facing interface was added** — M7 is entirely teacher-facing.
- **Existing worklist, student profile, and recommendation flows continue to work as before** — M7 adds new signals and a new query interface on top of the M6 foundation.

---

## Security & Compliance Notes

- Copilot responses are grounded only in teacher-scoped class data.
- Student names are not sent to the LLM in the copilot context.
- Copilot uncertainty is surfaced explicitly instead of fabricating conclusions when data is sparse.
- Accessibility metadata was tightened so student display names are not exposed in link `aria-label` attributes.

---

## What's Next

With M7 complete, the core milestone roadmap is finished through Closed Loop. The next release work should focus on post-M7 polish, scale, and any remaining cross-cutting work under MX.