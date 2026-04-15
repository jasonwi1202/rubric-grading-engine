# Feature: Essay Input

**Phase:** 1 — MVP
**Status:** Planned

---

## Purpose

Provide teachers with flexible, low-friction ways to get student writing into the system. Input is the entry point for the entire grading pipeline — if it's slow or broken, nothing else matters.

---

## User Story

> As a teacher, I want to submit student essays in whatever format I have them, so I can start grading without reformatting or copying content manually.

---

## Key Capabilities

### Text Paste
- Rich text and plain text paste support
- Preserve basic formatting (paragraphs, line breaks)
- Character and word count displayed on input

### File Upload
- Supported formats: PDF, DOCX, TXT
- Automatic text extraction with formatting cleanup
- Graceful handling of scanned PDFs (flag for review if OCR confidence is low)

### Google Docs Import
- OAuth-based read access to a shared Doc or folder
- Pull latest version of a document
- Detect if document has been updated since last import

### Bulk Input
- Upload a ZIP of files or a folder
- CSV/spreadsheet with student name + essay text columns
- Associate each essay with a student record on import

---

## Acceptance Criteria

- A teacher can paste an essay and see it rendered cleanly in under 2 seconds
- A teacher can upload a DOCX or PDF and receive extracted text with no manual cleanup required for standard formatting
- Bulk upload of 30 essays completes without errors and each essay is associated with the correct student
- Low-confidence OCR extractions are flagged and the teacher is prompted to review before grading proceeds

---

## Edge Cases & Risks

- Scanned PDFs with poor image quality may produce unreliable text — needs OCR confidence threshold and manual fallback
- DOCX files with complex layouts (tables, text boxes) may lose structure on extraction
- Google Docs permissions model requires careful OAuth scoping — read-only, no write access needed at this stage

---

## Open Questions

- Do we support handwriting recognition (photo upload of handwritten essays)?
- Should we support direct LMS submission import (Google Classroom assignments) in Phase 1 or defer to Phase 3?
- What is the maximum essay length we support, and does that affect cost/latency?
