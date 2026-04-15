# Feature: Automation Agents

**Phase:** 6 — Automation
**Status:** Planned

---

## Purpose

Reduce the manual steps a teacher must take to move through the grading and instruction cycle. Agents are not autonomous replacements for teacher judgment — they are background workers that handle routine operations, surface results, and prepare actions for the teacher to review and confirm. No agent takes a consequential action — grading, assigning, or communicating — without explicit teacher approval. The teacher remains in control at every step; the agents reduce the cost of exercising that control.

---

## User Story

> As a teacher, I want the system to handle routine preparation work and surface ready-to-review results, so I spend my time making decisions rather than doing mechanical work — but I always make the final call.

---

## Key Capabilities

### Grading Agent
- Runs grading when the teacher explicitly triggers it — either per essay or for the full batch
- Applies the assignment rubric and returns scored results to the teacher's review queue
- Flags low-confidence essays and surfaces them first in the review queue
- No grade is visible to anyone or recorded until the teacher reviews and approves it

### Intervention Agent
- Monitors student profiles for triggering conditions: persistent gaps, regression, non-response to feedback
- Prepares a recommended action (exercise, mini-lesson, worklist item) and surfaces it to the teacher for review
- Teacher approves, modifies, or dismisses each recommendation before anything is assigned or acted upon
- Nothing is sent to students, added to their workload, or reflected in their record without explicit teacher confirmation

### Teacher Copilot (Conversational Interface)
- Natural language interface for querying the system
- Example queries:
  - "Who is falling behind on thesis development?"
  - "What should I teach tomorrow based on this week's essays?"
  - "Which students haven't improved since my last feedback?"
- Returns ranked lists, summaries, or specific recommendations based on live data
- Does not take action — surfaces information and suggestions only

### Predictive Insights
- Identify students showing early signals of trajectory risk (declining trend, persistent low scores)
- Surface these proactively before they become urgent — not after
- Clearly labeled as predictive (not diagnostic) to set appropriate teacher expectations

---

## Acceptance Criteria

- When a teacher triggers grading on an assignment, results appear in the review queue within 60 seconds per essay
- The intervention agent surfaces a recommended action for any student who has been in the same skill gap group for 3 or more assignments — the teacher approves or dismisses it before any action is taken
- The teacher copilot correctly answers at least 4 of the 5 example queries above using real class data
- Predictive insights are labeled as predictions with a confidence indicator and supporting evidence

---

## Edge Cases & Risks

- Agents acting on stale data (e.g., recommending an intervention after the teacher already handled it manually) — agents must check current state before generating recommendations
- Teacher copilot confidently answering with incorrect information is more dangerous than not answering — it must express uncertainty and avoid fabricating data
- Grading agent failures must never silently drop essays — every failure must result in a teacher-visible error and a retry path
- Security: the teacher copilot must only access data for the requesting teacher's classes — cross-class data access is a critical boundary

---

## Open Questions

- Should the grading agent offer an optional auto-trigger mode (teacher opt-in) where grading starts on submission, or always require explicit teacher initiation?
- What is the escalation path when an agent produces a recommendation the teacher disagrees with repeatedly?
- Do we expose agent activity logs so teachers can see what the system did automatically and why?
