# Documentation

This folder contains all product and technical documentation for the Rubric Grading Engine. It is the source of truth for what the product does, why it exists, and how it is built.

---

## Structure

```
docs/
├── prd/                    # Product requirements
├── features/               # Feature specifications
├── architecture/           # Technical architecture
└── roadmap.md              # Milestones and GitHub issues
```

---

## Product Requirements

| Document | Description |
|---|---|
| [prd/product-vision.md](prd/product-vision.md) | One-line summary, problem statement, core loop, product pillars, HITL design principles, target users, value proposition, non-goals, strategic position, and phased roadmap |

---

## Feature Specifications

One document per feature. Each covers purpose, user story, key capabilities, acceptance criteria, edge cases, and open questions.

### Phase 1 — Foundation

| Document | Description |
|---|---|
| [features/rubric-builder.md](features/rubric-builder.md) | Criterion management, scoring scales, weighting, templates, and versioning |
| [features/essay-input.md](features/essay-input.md) | Text paste, file upload (PDF/DOCX/TXT), Google Docs import, and bulk input |
| [features/ai-grading-engine.md](features/ai-grading-engine.md) | Per-criterion scoring, weighted grade calculation, configurable strictness, and evidence grounding |
| [features/feedback-generator.md](features/feedback-generator.md) | Summary and criterion-level feedback, tone options, inline suggestions, and comment bank |
| [features/teacher-review.md](features/teacher-review.md) | Score override, feedback editing, grade lock, audit log, and review queue |
| [features/batch-grading.md](features/batch-grading.md) | Bulk submission, async queue processing, real-time progress tracking, and partial results |
| [features/export-share.md](features/export-share.md) | PDF and DOCX export, CSV grade export, clipboard copy, and LMS-compatible formats |
| [features/class-roster-student-management.md](features/class-roster-student-management.md) | Class creation, roster management, CSV/LMS import, student identity persistence, and auto-assignment |

### Phase 2 — Workflow

| Document | Description |
|---|---|
| [features/assignment-management.md](features/assignment-management.md) | Assignment creation, submission tracking, status workflow, analytics, and multi-class support |
| [features/confidence-scoring.md](features/confidence-scoring.md) | Per-criterion confidence levels, confidence-based review queue, fast-review mode, and confidence explanations |
| [features/academic-integrity.md](features/academic-integrity.md) | AI-generated content detection, plagiarism/similarity checking, paraphrase detection, and integrity reports |
| [features/regrade-requests.md](features/regrade-requests.md) | Teacher-mediated dispute logging, review queue, resolution actions, outcome tracking |
| [features/media-feedback.md](features/media-feedback.md) | In-browser voice and video comment recording, media comment bank, and export integration |

### Phase 3 — Student Intelligence

| Document | Description |
|---|---|
| [features/student-profiles.md](features/student-profiles.md) | Per-student skill breakdown, historical timeline, strengths and gaps, growth tracking, and teacher notes |
| [features/class-insights.md](features/class-insights.md) | Class performance summary, skill heatmap, common issues, score distribution, and cross-assignment trends |
| [features/writing-process-visibility.md](features/writing-process-visibility.md) | Composition timeline, session breakdown, content origin signals, version snapshots, and process-based insights |

### Phase 4 — Prioritization & Instruction

| Document | Description |
|---|---|
| [features/auto-grouping.md](features/auto-grouping.md) | Gap-based student grouping, group types, group stability tracking, and group actions |
| [features/teacher-worklist.md](features/teacher-worklist.md) | Ranked student queue, priority signals, suggested actions, completion tracking |
| [features/instruction-engine.md](features/instruction-engine.md) | Mini-lesson recommendations, targeted exercises, practice prompt generation, and intervention suggestions |
| [features/resubmission-loop.md](features/resubmission-loop.md) | Resubmission intake, version comparison, improvement tracking, feedback-addressed detection, and iteration history |

### Phase 5 — Closed Loop

| Document | Description |
|---|---|
| [features/automation-agents.md](features/automation-agents.md) | Grading agent, intervention agent, teacher copilot (conversational interface), and predictive insights |

### Infrastructure

| Document | Description |
|---|---|
| [features/platform-infrastructure.md](features/platform-infrastructure.md) | Platform-level infrastructure concerns not covered by individual features |

### Phase 0 — Public Website & Onboarding

| Document | Description |
|---|---|
| [features/public-website.md](features/public-website.md) | Landing page, product page, how-it-works, about, and public site layout and route structure |
| [features/pricing-page.md](features/pricing-page.md) | Pricing tiers, annual/monthly toggle, feature comparison table, FAQ, and school/district inquiry |
| [features/ai-transparency-page.md](features/ai-transparency-page.md) | How the AI grades, human-in-the-loop guarantee, data use disclosure, and AI accuracy explainer |
| [features/legal-pages.md](features/legal-pages.md) | Terms of Service, Privacy Policy, FERPA/COPPA notice, Data Processing Agreement, and AI Use Policy |
| [features/account-onboarding.md](features/account-onboarding.md) | Sign-up, email verification, onboarding wizard, trial lifecycle, and upgrade flow |

---

## Architecture

| Document | Description |
|---|---|
| [architecture/tech-stack.md](architecture/tech-stack.md) | Full stack: Next.js, FastAPI, PostgreSQL, Redis, Celery, S3 — with rationale for each choice |
| [architecture/backend-architecture.md](architecture/backend-architecture.md) | Process model, directory structure, layer responsibilities (routers → services → tasks), auth, and error handling |
| [architecture/frontend-architecture.md](architecture/frontend-architecture.md) | App Router structure, data fetching strategy, state management, API client pattern, and key component designs |
| [architecture/data-model.md](architecture/data-model.md) | All database entities with columns, types, indexes, relationships, and key design decisions |
| [architecture/data-flow.md](architecture/data-flow.md) | Step-by-step flows for: essay grading, skill profile update, batch export, integrity check, and authentication |
| [architecture/api-design.md](architecture/api-design.md) | Full REST endpoint reference, conventions, request/response shapes, and error codes |
| [architecture/data-ingestion.md](architecture/data-ingestion.md) | File extraction pipeline, student auto-assignment, LMS roster import, LLM response validation, and skill normalization |
| [architecture/configuration.md](architecture/configuration.md) | Every environment variable for backend and frontend, with defaults and descriptions |
| [architecture/performance.md](architecture/performance.md) | Performance targets per operation, bottleneck analysis, caching strategy, scaling approach, and monitoring metrics |
| [architecture/security.md](architecture/security.md) | Prompt injection defense, multi-tenant data isolation, authentication security, file upload safety, FERPA compliance, and API security |
| [architecture/testing-guide.md](architecture/testing-guide.md) | Testing strategy, tooling, conventions, and coverage targets for backend (pytest), frontend (Vitest), and E2E (Playwright) |
| [architecture/deployment.md](architecture/deployment.md) | Environment model, infrastructure overview, CI/CD pipeline, secrets management, rollback procedure, and DNS/TLS |
| [architecture/migrations.md](architecture/migrations.md) | Alembic migration workflow, zero-downtime migration patterns, data migration rules, and rollback procedures |
| [architecture/error-handling.md](architecture/error-handling.md) | Exception types, HTTP status mapping, Celery task failure patterns, logging rules, and frontend error handling |
| [architecture/llm-prompts.md](architecture/llm-prompts.md) | Prompt structure, versioning rules, JSON response contracts, injection defense, and failure handling for all three LLM operations |

---

## Roadmap

| Document | Description |
|---|---|
| [roadmap.md](roadmap.md) | GitHub milestones and issues across 5 product phases plus a cross-cutting section. Issues are sized for AI agent implementation. |

---

## Release Notes

| Document | Description |
|---|---|
| [release-notes/](release-notes/) | One file per completed milestone. Named `milestone-{number}.md`. Added as milestones ship. |

---

## Key Principles

A few decisions that cut across all documentation — read these before diving into any feature or architecture doc:

**Human-in-the-loop always.** The AI prepares; the teacher decides. No grade is recorded, no feedback shared, no exercise assigned, and no communication sent without explicit teacher approval. See [prd/product-vision.md](prd/product-vision.md#human-in-the-loop-design).

**Teacher-only interface.** There is no student-facing UI. All views and interactions are for the teacher. Student data is visible to teachers only.

**FERPA applies.** Student essay content and grades are education records. No student PII in logs, no student data sent to third-party services without a signed DPA, no data used for model training without explicit consent. See [architecture/security.md](architecture/security.md#5-ferpa-compliance).

**Rubric snapshots are immutable.** When a teacher creates an assignment, the rubric is snapshotted. Editing the rubric later does not affect grades already in progress. See [architecture/data-model.md](architecture/data-model.md#key-design-decisions).
