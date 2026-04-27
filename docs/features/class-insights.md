# Feature: Class Insights

**Phase:** 3 — Insights
**Status:** Implemented (M5-07 heatmap + M5-08 common issues / distribution UI)

---

## Purpose

Give teachers a class-level view of writing performance that surfaces patterns, not just averages. The goal is to help a teacher quickly understand: what is the class good at, where is the class struggling, and which students are outliers in either direction — without requiring them to interpret raw data.

---

## User Story

> As a teacher, I want to see how my class is performing as a whole on each writing skill, so I can identify what to reteach and which students need individual attention.

---

## Key Capabilities

### Class Performance Summary
- Average score per rubric dimension across the class
- Comparison to the teacher's target or prior assignment averages
- Overall class health indicator: on track, needs attention, significant concern

### Skill Heatmap
- Grid view: students as rows, rubric skills as columns
- Color-coded by performance level — instantly shows clusters of weakness
- Sortable by skill to see which students share the same gap

### Common Issues Across the Class
- Aggregated issue tags from AI feedback across all essays
- Ranked by frequency: "Evidence integration flagged in 18 of 28 essays"
- Direct link from issue to affected students

### Distribution View
- Score distribution histogram per criterion and overall
- Identify bimodal distributions (two distinct performance groups) — often a signal for differentiated instruction
- Outlier students highlighted at both ends of the distribution

### Cross-Assignment Trends
- Track class-level performance across multiple assignments over time
- Identify skills that are improving, plateauing, or declining at the class level
- Compare current class to previous cohorts on the same assignment (when data exists)

---

## Acceptance Criteria

- A teacher with at least one graded assignment can view a class performance summary showing per-skill averages
- The skill heatmap is readable for a class of up to 35 students without scrolling horizontally
- Common issues are ranked by frequency and each links to the list of affected students
- Cross-assignment trends are visible after at least 2 assignments have been graded

---

## Edge Cases & Risks

- Small classes (under 10 students) — averages are less meaningful; avoid implying statistical significance
- Classes with high absenteeism or missing submissions — partial data must be clearly labeled
- Different rubrics across assignments make cross-assignment comparisons complex — normalize or restrict comparisons to matching rubric dimensions

---

## Open Questions

- Should the class insights view feed directly into the Teacher Worklist feature as the source of prioritized actions?
- Do we surface class insights at the school or district level for administrators?
- Should the system automatically surface an insight when a meaningful pattern is detected (e.g., "Evidence scores dropped 20% from the last assignment")?
