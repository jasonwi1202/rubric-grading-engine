# Feature: Academic Integrity

**Phase:** 2 — Workflow
**Status:** Planned

---

## Purpose

Give teachers confidence that the essays they are grading represent the student's own work. Academic integrity checking is not the product's core differentiator, but its absence is a deal-breaker for most schools — teachers will not adopt a grading tool that ignores plagiarism and AI-generated writing. This feature must exist to get in the door; it does not need to be the best in class to be sufficient.

---

## User Story

> As a teacher, I want to know if a student's essay may be plagiarized or AI-generated before I spend time grading it, so I can address integrity issues rather than reward work that isn't the student's own.

---

## Key Capabilities

### AI-Generated Content Detection
- Analyze submitted essays for signals of AI authorship (ChatGPT, Claude, Gemini, etc.)
- Return a risk indicator: low, moderate, or high likelihood of AI generation
- Show which portions of the essay triggered the signal, not just an overall score
- Clearly label this as a signal for investigation, not a definitive finding — false positives exist and the teacher decides

### Plagiarism / Similarity Detection
- Compare submitted essays against:
  - Previously submitted essays in the same class (self-plagiarism and copying)
  - A corpus of web content and common student essay sources
- Return a similarity percentage and highlight matched passages
- Show the source of each match where identifiable

### AI Paraphrase Detection
- Detect essays that appear to be AI-generated text that has been lightly reworded or run through a "humanizer"
- Distinguish between clean AI output and paraphrased AI output where possible
- Flag for teacher review — do not auto-penalize

### Integrity Report
- Per-essay summary: AI likelihood, similarity score, flagged passages
- Separate from the grading report — integrity review is a distinct step
- Teacher can mark an essay as "reviewed — no action" or "flagged for follow-up"

### Class-Level Integrity Overview
- Summary view across all essays in an assignment: how many flagged, at what severity
- Useful for detecting coordinated cheating (multiple similar essays submitted)
- Outlier detection: one student's essay is unusually similar to another's

---

## Acceptance Criteria

- Every submitted essay receives an AI likelihood indicator and a similarity score before grading begins
- Flagged essays are surfaced in the review queue above unflagged essays
- The teacher can view highlighted passages and their source matches within the integrity report
- Integrity indicators are never shown to students — this is a teacher-only view
- The system never makes a definitive plagiarism finding — all language is framed as "signals" and "likelihood"

---

## Edge Cases & Risks

- False positives on AI detection are a serious reputational risk — a student wrongly accused damages trust in the tool and in the teacher. Framing and UI language must be extremely careful.
- Students who genuinely write in a structured, formulaic style may score higher on AI detection — the system must not penalize clear writing
- Similarity detection against a small class corpus is less reliable than against a large external database — be honest about corpus size limitations early on
- Legal and ethical exposure: the system must not be used as sole evidence in an academic misconduct case — documentation and human review are required

---

## Open Questions

- Do we build our own detection models or integrate a third-party service (e.g., Winston AI, Originality.ai, or similar)?
- What happens when a teacher flags an essay for integrity review — does that pause grading, or do both proceed in parallel?
- Should the system flag essays that show a dramatic improvement in quality from a student's historical baseline as a potential integrity signal?
- How do we handle false positive disputes — if a student or parent challenges an AI detection flag?
