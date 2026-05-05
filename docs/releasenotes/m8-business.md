# M8 Polish & Hardening — Business Release Notes

**Release**: v0.9.0  
**Milestone**: M8 — Polish & Hardening  
**Date**: May 2026  
**PRs**: #237–#241 (feature delivery), #244, #249–#252 (quality & release finalization)

---

## What's New for Teachers

### Interventions page

Intervention recommendations — previously generated automatically in the background — now have a dedicated home at `/dashboard/interventions`.

From this page you can:

- See all **pending** recommendations with the trigger reason, evidence summary, and suggested action
- **Approve** a recommendation with an optional note (approval is logged and visible in history)
- **Dismiss** a recommendation if it isn't relevant
- Review **approval history** to see what was actioned and when

Nothing happens to a student record until you take action. The page reflects the same human-in-the-loop guarantee as the rest of the platform.

### Text comment bank in the review panel

The review panel now includes a **text comment bank** alongside the existing media comment bank.

You can:

- **Save** any feedback you've written to the bank in one click
- **Search or browse** your saved snippets while reviewing another essay
- **Apply** a saved comment to fill in criterion feedback instantly

This is especially useful when the same feedback applies across multiple essays in a batch — write it once, apply it everywhere.

### Smarter dashboard navigation

The dashboard sidebar has been rebuilt from the ground up:

- **Class accordion** — your classes are listed directly in the sidebar; click to jump to any class without going back to the class list
- **Breadcrumbs** — every page shows a breadcrumb trail that reflects where you are (e.g., *Classes / AP English / Final Essay / Review queue*), populated from data already on screen — no extra loading
- **Mobile drawer** — on smaller screens, the hamburger menu opens a full-height navigation drawer with all the same links; Escape or clicking outside closes it; focus is managed correctly for keyboard and screen reader users

### Lesson planning on the class page

The class detail page now includes a **Lesson Planning** tab. It surfaces instruction recommendations for each skill-gap group and individual students, with Generate, Accept, and Dismiss controls — the same recommendations previously only visible via the student profile.

---

## Quality and reliability improvements

This milestone focused on closing gaps and raising the quality bar across the board.

### What got fixed or improved

- **Export error recovery** — if a batch PDF export fails, the UI now shows a clear error state and a retry button rather than silently stalling
- **Auth session recovery** — the frontend correctly recovers a session when an access token expires mid-session, without a visible flash or redirect to the login page
- **Worklist urgency tiers** — worklist items now display computed urgency levels (Critical / High / Medium) with color-coded indicators
- **Browser writing interface** — the in-browser essay composition tool was updated to use modern browser APIs; older behavior that produced browser console warnings has been removed

---

## Nothing changed for your data

All grades, rubrics, classes, essays, and student profiles from previous releases are fully compatible. No data migration is required to upgrade to this release.
