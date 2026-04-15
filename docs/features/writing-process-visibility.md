# Feature: Writing Process Visibility

**Phase:** 3 — Insights
**Status:** Planned

---

## Purpose

Give teachers insight into *how* a student wrote an essay, not just the final product. Writing process data — when work was done, how it evolved, whether content appeared in large pastes — is one of the strongest signals for both academic integrity and instructional insight. A student who wrote steadily over three sessions looks very different from one whose essay appeared in two large paste events the night before the deadline.

This feature is a meaningful differentiator. Turnitin's equivalent (Clarity) is one of their highest-value add-ons. For a product focused on writing instruction, process data is a natural fit — it tells teachers things the essay itself cannot.

---

## User Story

> As a teacher, I want to see how a student's essay developed over time — when they wrote, how content evolved, and whether the writing process looks authentic — so I can better understand whether the work reflects genuine effort and learning.

---

## Key Capabilities

### Composition Timeline
- Visual timeline of when the essay was written: editing sessions, gaps, and bursts of activity
- Shows incremental changes — the essay as it grew, not just the final version
- Highlights significant events: large paste insertions, mass deletions, rapid completion

### Session Breakdown
- Number of writing sessions and their duration
- Time between sessions (days or hours)
- Total active writing time vs. time the document was open but idle

### Content Origin Signals
- Flag large paste events: content added in a single operation rather than typed incrementally
- Flag rapid-completion events: essay goes from near-empty to near-complete in a very short session
- These are integrity signals, not findings — always framed as "warrants review"

### Version Snapshots
- View the essay at any point in its composition history
- Compare an early draft to the final submission
- Useful for instructional purposes: shows how a student's argument developed (or didn't)

### Process-Based Insights
- Students who write in short bursts close to the deadline may need time management support — not just writing support
- Students who wrote and revised extensively may have strong process skills even if the final product is weak
- Surface these as instructional insights alongside the rubric-based grading data

---

## Acceptance Criteria

- For any essay submitted through the system's native writing interface, a composition timeline is available to the teacher
- Large paste events and rapid-completion events are highlighted in the timeline with a plain-language description
- A teacher can view the essay at any saved snapshot point in its history
- Process insights (e.g., "Written in a single 20-minute session") appear alongside the graded essay in the review interface

---

## Edge Cases & Risks

- Essays submitted as file uploads have no process data — this feature only applies to essays written inside the system's writing interface. This limitation must be clearly communicated.
- Privacy: keystroke-level logging is invasive if students are not informed. Clear disclosure at essay submission time is required.
- Process data can be misleading — a student who pastes from their own notes app is not cheating. The system must not conflate paste events with plagiarism automatically.
- Students writing in a second language may have different process patterns (more pausing, more revision) — avoid designing anomaly thresholds that penalize non-native writers

---

## Open Questions

- Does this feature require a native in-browser writing interface, or can we instrument a Google Docs integration to capture process data?
- Should process data feed into the academic integrity report or remain a separate instructional signal?
- Should process patterns (e.g., consistent last-minute writing) be surfaced in the teacher worklist as a time management signal alongside skill gap signals?
