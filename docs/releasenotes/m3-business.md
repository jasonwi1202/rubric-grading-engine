# M3 Release Notes — Business Summary

**Version:** v0.4.0  
**Milestone:** M3 — Foundation  
**Status:** Pending merge to main

---

## What Was Delivered

Milestone 3 delivers the core grading product. Before this milestone, teachers could create accounts and navigate the marketing site, but could not do any actual grading work. M3 closes that gap: teachers can now build rubrics, manage classes and rosters, upload essays, trigger AI grading, and access per-criterion AI feedback with scores and written justifications.

### Rubric Builder

Teachers can now create and manage rubrics directly in the product:

- **Drag-and-drop criterion editor** — add, remove, reorder, and configure criteria with names, descriptions, anchor text, and score ranges; live weight indicator enforces 100% total
- **Personal templates** — save any rubric as a reusable template for future assignments
- **System starter templates** — 3 built-in templates (5-paragraph essay, argumentative essay, research paper) to reduce setup time for common assignment types
- **Rubric snapshots** — when an assignment is created, the rubric is snapshotted permanently; editing the rubric later has no effect on in-progress grades

### Class & Roster Management

- Create and manage classes with academic year tagging
- Add students individually or import a full roster from CSV
- CSV import shows a diff (new / updated / skipped) for teacher confirmation before any changes are saved — no accidental overwrites
- Soft-remove students from a class without deleting their records
- Student records persist independently of class enrollments — a student transferred between classes retains their history

### Essay Upload & Student Matching

- Upload PDFs, Word documents, or plain text files via drag-and-drop or file picker (single or batch)
- The system automatically tries to match each essay to a student in the class roster using filename, document author metadata, and header text
- Auto-matches above 85% confidence are applied immediately; uncertain matches are held for manual review
- Teachers can correct any match before grading begins — no grade is associated with a wrong student

### AI Grading Engine

The grading pipeline is fully operational end-to-end:

1. Teacher clicks "Grade now" on any assignment with uploaded essays
2. The system enqueues a grading task for each essay in parallel
3. Each essay is evaluated against the assignment's rubric snapshot by the AI
4. The AI returns a score for every criterion and a written justification for each score
5. An overall summary feedback paragraph is generated for the student
6. Feedback tone is configurable per assignment: encouraging, direct, or academic
7. A real-time progress bar shows grading status for every essay, updating every 3 seconds
8. Failed essays surface a "Retry" button — teachers never need to restart the whole batch

### Human-in-the-Loop Safeguards

The AI prepares grades; teachers decide what to record. This principle is enforced throughout:

- **No grade is recorded without teacher action** — AI output is draft until the teacher explicitly locks it
- **Every score can be overridden** — teachers can change any criterion score before locking
- **Every feedback note can be edited** — teachers can rewrite any AI-generated text
- **Grades are locked, not submitted** — locking is a teacher-initiated action; locked grades are read-only
- **Every edit is audited** — before/after values recorded for every score override and feedback edit, with timestamp and actor

### Comment Bank

- Teachers can save any feedback snippet to a personal comment bank for reuse
- When editing feedback for a new essay, the system suggests saved comments that match the current criterion and issue type

### Prompt Injection Defense

Student essays are untrusted content. M3 implements the full defense required by the project security standard:

- Essay text is always sent in the AI `user` role — never embedded in the system prompt
- The system prompt explicitly instructs the AI to ignore any directives found within the essay text
- Essay text is delimited with explicit `<ESSAY_START>` / `<ESSAY_END>` tags
- Every AI response is validated against the expected grading schema before anything is written to the database — a non-conforming response is retried or rejected, never written as-is
- AI scores are always clamped server-side to the rubric's configured range — the AI cannot return an out-of-range score that gets stored

### Teacher Grade Review Interface

Teachers now have a full UI to review, correct, and finalize every AI grade:

- **Two-panel review layout** — essay text on the left, per-criterion AI scores and written justifications on the right
- **Inline score override** — click any criterion score to change it; the weighted total updates in real time
- **Inline feedback editor** — edit any AI-generated feedback note directly in the panel
- **Lock grade button** — explicitly lock a grade when review is complete; locked grades are read-only
- **Review queue** — list view of all essays in an assignment with status badges (unreviewed / in-review / locked); sortable and filterable by status, score range, and student; keyboard-navigable
- **Audit trail** — every score override and feedback edit is recorded with a timestamp, actor, and before/after values; the full history is accessible per grade

### Export

Teachers can now get grades and feedback out of the system:

- **PDF batch export** — one click generates a per-student feedback PDF for every locked grade in the assignment, packaged as a ZIP file and downloaded directly; progress shown while the export runs
- **CSV grade export** — download a spreadsheet of all locked grades (student name, per-criterion scores, weighted total) compatible with common LMS gradebook import formats
- **Clipboard copy** — copy an individual student's feedback to the clipboard for pasting into any other system

---

## Who Can Use This Now

Any teacher with an account can complete the full grading workflow end-to-end:

1. Create a class and import or add students
2. Build a rubric (or start from a template)
3. Create an assignment and attach the rubric
4. Upload essays for any or all students
5. Confirm or correct student–essay matches
6. Trigger AI grading and watch the progress in real time
7. Review per-criterion AI scores and written justifications in the two-panel review interface
8. Override any score or edit any feedback note before locking
9. Lock grades when satisfied with the review
10. Export feedback as PDF ZIPs or CSV gradebook files
