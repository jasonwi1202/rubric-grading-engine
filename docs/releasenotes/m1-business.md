# M1 Release Notes — Business Summary

**Milestone:** M1 — Project Scaffold
**Version:** v0.2.0 (pending merge to `main`)
**Release date:** TBD (upon PR merge)
**Audience:** Product, stakeholders, non-technical reviewers

---

## What Was Delivered

M1 is the foundational infrastructure milestone. It does not deliver any visible teacher-facing features — its purpose is to build the technical platform that all subsequent milestones build on. Think of it as constructing the building before furnishing any rooms.

### What is now in place

**A working backend API service**
The FastAPI backend starts, responds to a health check, and returns structured error messages for every failure scenario. The application is configured entirely through environment variables — no secrets are hardcoded anywhere in the codebase.

**A working frontend shell**
The Next.js frontend loads, routes teachers to the correct pages, and protects the dashboard from unauthenticated access. A login page exists. The routing infrastructure for the public website (`/(public)/`) and the teacher dashboard (`/(dashboard)/`) is in place.

**A secure authentication plumbing layer**
The frontend and backend have the wiring needed to support authentication: typed API client, in-memory token management, silent token refresh, and a middleware layer that enforces login before any dashboard route loads. The actual login endpoints (JWT issuance) are scheduled for M2 (onboarding/sign-up milestone).

**A database migration system**
Alembic is configured and connected to PostgreSQL. The team can write and run database migrations from this point forward. No application tables exist yet — those come in M3.

**A background task queue**
Celery and Redis are connected. Background tasks (used for grading, email, exports) can be written and deployed from this point forward.

**File storage**
The system can upload files to S3-compatible storage (AWS S3 in production, MinIO in development) and generate time-limited signed URLs for retrieval. This is the foundation for essay file uploads in M3.

**A CI/CD pipeline that is already running**
Every pull request runs: Python linting, type checking, backend tests, frontend linting, TypeScript type checking, frontend tests, and security audits (`pip-audit`, `npm audit`). All checks must pass before a PR can merge.

---

## What This Milestone Does NOT Include

- Teacher login is not yet functional end-to-end (JWT issuance backend is M3 scope)
- No rubrics, classes, students, essays, or grades — those are M3
- No public marketing pages — those are M2
- No AI grading — that is M3
- Nothing visible to a teacher or administrator yet

---

## Notable Decisions Made

**Next.js upgraded from v14 to v15** during this milestone after `npm audit` flagged two denial-of-service CVEs in Next.js 14. The upgrade was applied before any production code was written on top of it, making this the right time to take it.

**S3 object keys are never logged.** The team established the rule early: any data that could identify a student (including file paths that could contain student names) does not appear in logs or error messages.

---

## What Comes Next

**M2 — Public Website & Onboarding** can begin immediately. It delivers the marketing site, legal pages, pricing, sign-up flow, and trial onboarding wizard.

**M3 — Foundation** is the core product milestone: rubrics, grading, teacher review, and export. It can begin once the M1 database and backend foundation is confirmed stable.
