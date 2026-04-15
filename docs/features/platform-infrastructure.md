# Feature: Platform & Infrastructure

**Phase:** Cross-cutting
**Status:** Planned

---

## Purpose

Define the platform-level capabilities that support all product features: multi-class support, school/district administration, third-party integrations, and auditability. These are not user-facing features in isolation — they are the structural requirements that determine whether the product can scale from one teacher to an institution.

---

## User Story

> As a teacher, I want to manage multiple classes separately without data mixing. As a school administrator, I want visibility into how writing performance is trending across my building. As a compliance-conscious institution, I want to know that every grade can be traced back to its source.

---

## Key Capabilities

### Multi-Class Support
- Teachers can create and manage multiple classes independently
- Each class has its own roster, assignments, and gradebook
- Data never crosses between classes unless explicitly shared
- Quick class-switcher in the navigation — no full page reload

### School / District Layer
- Admin accounts with read-only visibility across teachers and classes
- Aggregated performance dashboards: school-level writing trends by skill
- Usage tracking: which teachers are active, which assignments have been run
- No admin access to individual student essay content — aggregate data only

### LMS Integrations
- **Google Classroom:** assignment sync, roster import, grade passback
- **Canvas:** assignment and grade integration via LTI or API
- **Microsoft Teams for Education:** assignment creation and feedback delivery
- Integration priority: Google Classroom first (highest adoption in target market)

### Auditability
- Every grade has a full audit trail: AI score → teacher edits → final locked grade
- Every piece of feedback is tracked: AI-generated vs. teacher-written vs. teacher-edited
- Audit log is exportable per assignment for school records
- Audit data is immutable — cannot be deleted by teachers or admins

### Data Privacy & Compliance
- Student data stored and processed in compliance with FERPA (US) and applicable state privacy laws
- No student PII used for AI model training without explicit opt-in consent
- Data retention policies configurable at the school/district level
- Clear data deletion workflow when a student leaves the school

### Access Control
- Role-based access: teacher, co-teacher, read-only observer, school admin, district admin
- Co-teacher role: full access to a shared class
- Observer role: read-only access to class data (for instructional coaches, department heads)

---

## Acceptance Criteria

- A teacher with 5 classes can switch between them in under 2 clicks with no data mixing
- An admin account can view aggregated skill performance across all teachers without accessing individual student essays
- Google Classroom integration can import a class roster and sync an assignment in under 3 minutes
- The full audit trail for any grade is accessible to the teacher and exportable as a CSV

---

## Edge Cases & Risks

- Schools with non-standard LMS setups (self-hosted Canvas, legacy systems) — integrations must be configurable, not hardcoded
- FERPA requirements restrict what data can be stored and for how long — must be reviewed with legal counsel before launch to schools
- District-level deployments may require SSO (SAML, Google SSO) — authentication architecture must support this from the start

---

## Open Questions

- Which LMS integration ships with Phase 2 vs. Phase 3? Google Classroom is the clear first priority.
- Do we support student login accounts, or is the product purely teacher-facing for the initial phases?
- What is the data retention default, and who can change it — the teacher, the school admin, or only at the district level?
