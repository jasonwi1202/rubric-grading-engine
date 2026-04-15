# Feature: Assignment Management

**Phase:** 2 — Workflow
**Status:** Planned

---

## Purpose

Give teachers a structured way to organize grading work by assignment, track submission status across students, and understand performance results at the assignment level. Without this layer, the system is a grading tool. With it, it becomes part of the teacher's instructional workflow.

---

## User Story

> As a teacher, I want to manage my assignments in one place — from creating them to tracking who has submitted, to reviewing overall results — so I always know where things stand.

---

## Key Capabilities

### Assignment Creation
- Create an assignment with: title, due date, class, and attached rubric
- Optional: assignment prompt text (visible to teacher, used as grading context)
- Assignments are the container for all related essays and results

### Submission Tracking
- Class roster view showing who has submitted, who hasn't, and submission timestamps
- Filter by: submitted, pending, graded, returned
- Manual override for offline submissions (mark as submitted without file upload)

### Assignment Analytics
- Score distribution across the class (histogram)
- Class average per rubric criterion
- Most common issues across all essays (aggregated from feedback tags)
- Outlier detection: students significantly above or below the class average

### Assignment Status Workflow
- States: draft → open → grading → review → complete → returned
- Teacher moves through states explicitly — nothing is returned to students automatically
- Clear visual indicator of which state an assignment is in

### Multi-Class Support
- An assignment can be created for one class or duplicated to multiple classes
- Each class instance tracks submissions and grades independently
- Compare results across classes on the same assignment

---

## Acceptance Criteria

- A teacher can create an assignment, attach a rubric, and see the full class submission status in one view
- Assignment analytics are available as soon as 50% of essays have been graded
- The teacher can view a score distribution chart and identify the top 3 most common issues for any assignment
- Assignment state transitions are explicit and logged

---

## Edge Cases & Risks

- Students submitting after the due date — system should flag late submissions but not block them
- Rubric changes after an assignment opens — should warn teacher that existing grades may be inconsistent
- Large classes with many missing submissions — roster view must handle sparse data gracefully

---

## Open Questions

- Should the system send reminders or notifications to teachers about overdue reviews?
- Do we support co-teacher access to the same assignment in Phase 2?
- Should assignment analytics feed directly into the class insights and student profile features?
