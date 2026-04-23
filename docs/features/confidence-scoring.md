# Feature: Confidence Scoring

**Phase:** 2 — Workflow
**Status:** Partially Implemented (M4.2)

**Shipped:**
- Per-criterion low-confidence explanation callout in the essay review panel (`EssayReviewPanel`) — active today, no backend change needed
- Queue-level UI: confidence badges, confidence sort (with deterministic tie-breaker), fast-review toggle, low-confidence filter, and bulk-approve — code is complete and degrades gracefully; these features activate automatically once the backend essay list endpoint (`GET /assignments/{id}/essays`) returns `overall_confidence` per essay

**Pending backend support (not yet active):**
- `GET /assignments/{id}/essays` does not yet return `overall_confidence` (or `grade_id` / score summary fields); fast-review and low-confidence filter are hidden in the UI until at least one essay carries confidence data
- Teacher-configurable confidence thresholds
- Borderline-grade (score-band) flagging

---

## Purpose

Surface the AI's uncertainty so teachers can spend their review time where it matters most. Not all essays need the same level of scrutiny — some grades are clear-cut, others are genuinely ambiguous. Confidence scoring makes that distinction visible and drives a smarter review workflow.

---

## User Story

> As a teacher, I want to know which grades the AI is least sure about, so I can focus my review time on the essays that actually need my judgment.

---

## Key Capabilities

### Per-Criterion Confidence
- Each criterion score carries a confidence level: high, medium, or low
- Confidence reflects how clearly the essay evidence maps to the rubric criteria
- Low confidence triggers a flag in the review interface

### Assignment-Level Confidence Summary
- Each essay in the batch review queue shows an overall confidence indicator
- Teacher can sort the queue by confidence — low confidence essays surface first
- High-confidence essays can be bulk-approved with a single action

### Confidence Thresholds
- Teacher-configurable thresholds for what counts as "needs review"
- Default: flag any essay with one or more low-confidence criterion scores
- Option to flag essays where the total score falls within a narrow band (borderline grades)

### Skip High-Confidence Items
- Dedicated "fast review" mode: show only low-confidence essays
- Teacher reviews and confirms each high-confidence essay — or bulk-approves the group in a single action
- High-confidence essays are locked only after the teacher explicitly approves them, individually or as a batch — never locked automatically

### Confidence Explanation
- When a criterion is flagged low-confidence, show why: ambiguous evidence, missing content, conflicting signals
- Teacher sees the same reasoning the AI used to arrive at the uncertain score

---

## Acceptance Criteria

- Every graded essay displays an overall confidence indicator in the review queue
- The teacher can filter the queue to show only essays below a confidence threshold
- Bulk approval of high-confidence essays locks them in a single action
- Low-confidence flags include a plain-language explanation of why the AI was uncertain

---

## Edge Cases & Risks

- Confidence scores may be miscalibrated early — a confident but wrong score is more dangerous than an uncertain one. Monitor override rates on high-confidence items.
- Teachers who skip review of high-confidence items take on implicit trust in the AI — the system should make this tradeoff explicit and trackable
- Confidence thresholds that are too sensitive create noise; too permissive create risk — defaults need empirical tuning

---

## Open Questions

- Should confidence scores be visible to students in their feedback, or only to teachers?
- Do we track whether teacher overrides correlate with confidence levels over time, and surface that as a quality signal?
- Can confidence calibration be personalized per teacher based on their override history?
