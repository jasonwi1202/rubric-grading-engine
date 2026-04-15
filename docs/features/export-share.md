# Feature: Export & Share

**Phase:** 1 — MVP
**Status:** Planned

---

## Purpose

Give teachers a reliable way to deliver graded feedback to students and integrate results with their existing workflows. Export is the last step in the grading loop — if it's friction-heavy, teachers will abandon the tool before students ever see the output.

---

## User Story

> As a teacher, I want to share finalized grades and feedback with students in a format that works with how I already deliver work, without manual copying or reformatting.

---

## Key Capabilities

### Copy to Clipboard
- Copy an individual student's feedback as formatted text in one click
- Paste-ready for email, Google Classroom comment, or any LMS message field

### PDF Export
- Export a single student's graded feedback as a formatted PDF
- Include: student name, assignment title, rubric scores, total grade, and all feedback text
- Batch export: download a ZIP of PDFs for all students in an assignment

### DOCX Export
- Export feedback as a Word document for teachers who prefer that format
- Editable post-export if further customization is needed

### CSV Grade Export
- Export a grade sheet: student name, per-criterion scores, total grade
- Compatible with Google Sheets, Excel, and LMS gradebook imports

### LMS Integration (Manual, Phase 1)
- Export instructions for posting grades to Google Classroom and Canvas manually
- Copy-paste optimized format for LMS comment fields

### Shareable Student Report (Later)
- Generate a read-only link to a student's feedback report
- Teacher controls visibility — not active by default

---

## Acceptance Criteria

- A teacher can export a PDF for a single student in one click from the review interface
- Batch PDF export for a class of 30 produces a correctly named ZIP file in under 30 seconds
- CSV export matches the scores visible in the review interface exactly
- Exported documents include the assignment name, student name, rubric scores, and all feedback text

---

## Edge Cases & Risks

- PDF formatting must handle long feedback text without overflow or truncation
- Exported grades must match what is in the system — no rounding differences between display and export
- Teachers in FERPA-regulated environments may have restrictions on where student data can be sent — shareable links need careful access control design

---

## Open Questions

- Should we support direct LMS gradebook push (API-based) in Phase 2, starting with Google Classroom?
- Do students ever log in to view their own feedback directly, or is delivery always teacher-mediated?
- Should exported PDFs include the rubric structure itself or just the scores and feedback?
