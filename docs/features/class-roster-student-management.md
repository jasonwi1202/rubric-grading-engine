# Feature: Class Roster & Student Management

**Phase:** 1 — MVP
**Status:** UI implemented (M3.8); backend APIs in M3.5–M3.7

---

## Purpose

Define and manage the core data structure that makes longitudinal student tracking possible: classes scoped to an academic year, with rosters of students whose identities and writing histories persist across time. Without this foundation, the system can grade essays but cannot track progress — it has no memory of who a student is from one assignment to the next, or one year to the next.

This feature is the data backbone for Student Profiles, Auto-Grouping, the Teacher Worklist, and every other insight feature.

---

## User Story

> As a teacher, I want to organize my students into classes tied to a school year, so that writing progress is tracked per student over time — across assignments, across semesters, and across years.

---

## Key Capabilities

### Academic Year Scoping
- Every class belongs to an academic year (e.g., 2024–25, 2025–26)
- Year is set at class creation; all assignments and grades under that class inherit the year context
- Historical years remain accessible in read-only mode — a teacher can look back at prior year data
- Year-over-year comparison: view a student's skill profile from last year alongside this year

### Class Creation & Management
- Create a class with: name, subject, grade level, academic year
- Multiple classes per teacher, per year (e.g., "Period 2 English — 2025–26", "AP Lang — 2025–26")
- Archive a class at end of year — data preserved, class no longer appears in active views
- Duplicate a class structure (without student data) to scaffold the next year's setup

### Roster Management
- Add students manually by name or import from CSV or LMS (Google Classroom, Canvas)
- Remove a student from a class (does not delete their history — data is preserved)
- Transfer a student between classes within the same year, carrying their assignment history
- Handle mid-year enrollments — student joins a class, prior assignments show as N/A, future ones are tracked

### Student Identity & Persistence
- Students exist as persistent records independent of any single class
- The same student can appear in multiple classes across multiple years under one identity
- A student's full writing history — across all classes and years — is accessible from their profile
- Student records are not deleted when removed from a class or when a class is archived

### Essay-to-Student Assignment

**Auto-Assignment**
- When essays are uploaded in bulk, the system attempts to match each file to a student in the roster
- Match signals: filename containing student name, metadata in DOCX/PDF, header text in the essay body
- Confidence threshold: auto-assign only when match confidence is high; flag uncertain matches for review

**Manual Assignment**
- Teacher reviews all unassigned or low-confidence essays in a dedicated assignment queue
- Drag-and-drop or dropdown to assign an essay to a specific student
- Once assigned, the essay is linked to that student's permanent record

**Unassigned Essay Handling**
- Essays that cannot be matched automatically are held in an "unassigned" queue
- Grading can proceed on unassigned essays, but results do not feed into student profiles until assigned
- Teacher is notified of unassigned essays before closing a grading batch

### Roster Sync with LMS
- Import roster directly from Google Classroom or Canvas (no manual CSV needed)
- Sync on demand: teacher can refresh the roster to pull in newly enrolled students
- Conflicts between imported and local roster data are surfaced for teacher resolution, not silently overwritten

---

## Acceptance Criteria

- A teacher can create a class for a specific academic year and add students within 3 minutes
- Bulk essay upload triggers auto-assignment, with high-confidence matches applied automatically and uncertain matches flagged for manual review
- A teacher can manually assign any unassigned essay to a student in the roster in a single action
- A student's full history — across all classes and years — is accessible from their profile page
- Archiving a class at year-end removes it from active views without deleting any student data
- A student transferred between classes retains all assignment history from the original class

---

## Edge Cases & Risks

- **Name collisions:** Two students with the same name in the same class — auto-assignment must not silently pick the wrong one; flag for manual review
- **Anonymous or pseudonymous submissions:** Some teachers collect essays without names to reduce bias — the system must support a "name blind" grading mode where assignment happens after grading
- **Homeschool or non-standard setups:** Single-teacher, single-student classes are valid — the system must not require a minimum roster size
- **Student leaves mid-year:** Data must be preserved and visible even after the student is removed; removal is a soft operation
- **Same student, multiple teachers:** A student in two different teachers' classes in the same year — each teacher sees their own class view; student profile aggregates across both

---

## Open Questions

- Does a student record have a login/identity of its own, or is it purely teacher-managed in Phase 1?
- When a teacher views a student who was also in another teacher's class, do they see cross-class data or only their own?
- Should the system support "promoting" a roster from one year to the next — automatically creating the new year's class with the same students?
- How do we handle students whose names change (e.g., legal name update mid-year)?
