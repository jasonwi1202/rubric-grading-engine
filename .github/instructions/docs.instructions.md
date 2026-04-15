---
applyTo: "docs/**"
---

# Documentation Review Instructions

When reviewing a PR that touches `docs/**`, check every item below.

## Accuracy

- [ ] Any described behavior matches actual or planned implementation — no aspirational claims presented as current fact
- [ ] API endpoint paths, field names, and HTTP methods match `docs/architecture/api-design.md`
- [ ] Data model column names and types match `docs/architecture/data-model.md`
- [ ] Environment variable names match `docs/architecture/configuration.md`

## Core Principles Not Violated

Documentation must never contradict these foundational principles:

- [ ] Human-in-the-loop: no doc describes the AI taking a consequential action without teacher approval
- [ ] Teacher-only interface: no doc describes student-facing views, student accounts, or student-accessible endpoints
- [ ] Rubric snapshots are immutable: no doc suggests editing a rubric affects grades already in progress
- [ ] FERPA: no doc suggests student data is used for any purpose beyond grading and instruction

## Roadmap & Issue Changes

For changes to `docs/roadmap.md`:

- [ ] New issues are sized for a single AI coding agent session (one layer or one feature area)
- [ ] `[BLOCKER]` tags are accurate — only mark an issue as a blocker if dependent issues genuinely cannot start without it
- [ ] Milestone assignments are correct per the phase definitions in `docs/prd/product-vision.md`
- [ ] Issue numbers do not conflict with existing entries

## Architecture Doc Changes

For changes to `docs/architecture/**`:

- [ ] The change is consistent with the tech stack defined in `docs/architecture/tech-stack.md`
- [ ] Security implications of any new pattern are addressed — if the change introduces a new data flow, `security.md` is updated too
- [ ] If a migration pattern is added or changed, `migrations.md` is consistent

## Links

- [ ] All internal `[doc links](path/to/doc.md)` resolve to files that exist
- [ ] No broken anchor links (`#section-name`) — verify the heading exists in the target file
