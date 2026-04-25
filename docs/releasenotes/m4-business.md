# M4 Workflow — Business Release Notes

**Release**: v0.5.0  
**Milestone**: M4 — Workflow  
**Date**: April 2026  
**PRs**: #132–#151 (20 pull requests)

---

## What's New for Teachers

### Grading confidence indicators

The AI now tells you how confident it is in each criterion score — high, medium, or low. The review queue surfaces this clearly: low-confidence essays float to the top by default so you can focus your attention where the AI is least sure. A fast-review mode lets you filter to only those essays. For high-confidence batches, a single bulk-approve action lets you confirm them all at once — but you always have to click it explicitly. Nothing approves automatically.

### Academic integrity signals

Every submitted essay is now checked for similarity against other submissions in the same assignment. You'll see a similarity score and any flagged passages highlighted directly in the essay review panel. You can also connect a third-party integrity provider (Originality.ai or Winston AI) for AI-generated content detection — configurable without any code changes.

All language in the interface is framed as signals, not findings. The system does not make conclusions; it surfaces information for your professional judgment.

### Regrade requests

You can now log a regrade request on behalf of a student directly from the essay review panel. The assignment page has a new regrade queue where you can see all open requests, review the original score alongside the dispute, and either approve a score change or deny with a written note. Submission windows and per-grade limits are configurable. Every resolution is audit-logged.

### Audio and video feedback comments

Record a voice or video message attached to any graded essay — up to 3 minutes. This gives you a richer way to deliver nuanced feedback than text alone, especially for complex writing issues that are hard to summarize briefly. You can save frequently-used comments to a bank and apply them to other essays in one click. Media comments are included as a link or QR code in the PDF export so teachers using print workflows can still reference them.

---

## Cross-Cutting Quality Work

These improvements shipped alongside M4 and apply to the whole product:

- **Security hardening**: rate limiting on login and sign-up, additional security response headers on every page, and row-level security at the database layer ensuring that teacher data is isolated at the deepest level.
- **Observability**: every API request now carries a correlation ID that threads through all log lines and background tasks, making it much easier to trace what happened during any given grading session.
- **E2E test coverage**: four critical user journeys are now covered by automated end-to-end tests — the setup flow, batch grading, the review-and-lock flow (our core human-in-the-loop guarantee), and export. These run in CI on every PR.
- **Accessibility**: keyboard navigation, ARIA labels, and focus management have been audited and verified across the grading interface. The `axe-core` accessibility scanner runs automatically on every CI build.

---

## What's Next (M5 — Student Intelligence)

M5 builds persistent skill profiles for each student. After grades are locked, the system will normalize scores across rubric criteria into six canonical skill dimensions (thesis, evidence, organization, analysis, mechanics, voice), build a longitudinal profile per student, and surface a skill heatmap for the whole class. Teachers will be able to see at a glance which students are improving and where the class is struggling collectively.
