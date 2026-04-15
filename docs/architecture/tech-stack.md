# Tech Stack

## Overview

This document defines the canonical technology choices for the Rubric Grading Engine and the reasoning behind each decision. All architectural decisions should be made in the context of this stack.

---

## Stack Summary

| Layer | Technology | Version Target |
|---|---|---|
| Frontend | Next.js + TypeScript | Next.js 14+ (App Router) |
| Backend API | FastAPI + Python | Python 3.12+, FastAPI 0.110+ |
| Database | PostgreSQL | 16+ |
| Cache / Queue Broker | Redis | 7+ |
| Async Task Queue | Celery | 5+ |
| Containerization | Docker + Docker Compose | Local dev |
| AI / LLM | OpenAI API (primary) | Model-configurable |
| File Storage | S3-compatible object storage | AWS S3 or local MinIO for dev |

---

## Frontend

### Next.js 14+ with TypeScript
- **App Router** for file-based routing, layouts, and server components
- **TypeScript** throughout — no exceptions
- **Server Components** for data-heavy read views (class dashboard, student profiles)
- **Client Components** for interactive review interfaces (essay grading, score overrides)
- **Server Actions** for form submissions and mutations where appropriate

### UI & Styling
- **Tailwind CSS** for utility-first styling
- **shadcn/ui** for accessible component primitives (built on Radix UI)
- No heavy component library — keep the bundle lean and the UI fully controllable

### State Management
- **React Query (TanStack Query)** for server state, caching, and background refetching
- Avoid global client state stores (Redux, Zustand) unless a clear need emerges
- Form state: **React Hook Form** + **Zod** for validation

### Key Frontend Constraints
- All grading and data actions go through the FastAPI backend — Next.js does not write directly to the database
- No AI calls from the frontend — all LLM interactions are server-side only
- Teacher authentication is handled via the backend; Next.js middleware enforces route protection

---

## Backend

### FastAPI + Python 3.12+
- **Async-first** — all route handlers are async; blocking operations (file I/O, DB queries) use async drivers
- **Pydantic v2** for request/response validation and serialization
- **SQLAlchemy 2.0** (async) as the ORM with Alembic for migrations
- **asyncpg** as the PostgreSQL async driver

### Async Task Queue — Celery + Redis
- Grading jobs, batch processing, and integrity checks run as Celery tasks
- Redis serves as both the Celery broker and result backend
- Workers are separate processes — FastAPI enqueues, workers execute
- This keeps API response times fast regardless of essay volume

### Why Celery over Temporal (for now)
Temporal provides durable, resumable workflows with full audit history — ideal for the agent/automation layer in Phase 6. For Phases 1–4, Celery + Redis is simpler to operate and sufficient for the job queue needs. Temporal will be evaluated when multi-step agentic workflows are built.

---

## Database

### PostgreSQL 16+
- Primary datastore for all relational data: users, classes, students, assignments, essays, rubrics, grades, feedback, profiles
- **pgvector** extension for storing and querying essay/feedback embeddings (used for similarity detection and comment bank suggestions)
- Row-level security (RLS) as an additional defense-in-depth layer for multi-tenant data isolation
- Connection pooling via **PgBouncer** in production

### What goes in Postgres
- All structured application data
- Audit logs (append-only tables)
- Essay text (stored as text fields, not in object storage — keeps queries simple)
- Grading results, scores, feedback text
- Student skill profiles (aggregated scores as JSONB)

### What does NOT go in Postgres
- Binary files (PDFs, DOCX uploads) — these go to object storage
- Audio/video media comments — object storage
- Celery task state — Redis

---

## Cache & Message Broker

### Redis 7+
- **Celery broker and result backend** — primary use case
- **Session cache** — teacher session data and short-lived tokens
- **Batch progress state** — real-time grading progress updates (polled by the frontend)
- **Rate limiting** — per-teacher API rate limits for AI-heavy endpoints

Redis is not optional for this architecture. The async grading pipeline depends on it.

---

## File Storage

### S3-Compatible Object Storage
- Uploaded PDFs and DOCX files
- Exported PDFs and ZIPs
- Audio/video media comment files
- **Local dev:** MinIO (S3-compatible, runs in Docker)
- **Production:** AWS S3 or equivalent

---

## AI / LLM Integration

### OpenAI API (Primary)
- All grading, feedback generation, and instruction recommendations go through the LLM
- Model is configurable per environment — do not hardcode model names in application logic
- Prompt templates are stored as versioned configuration, not hardcoded strings
- All LLM calls are made server-side from FastAPI workers — never from the frontend or directly from the database

### Academic Integrity Detection
- AI-generated content detection: third-party API integration (TBD — evaluate Winston AI, Originality.ai, or similar)
- Plagiarism/similarity: third-party API or internal cross-submission comparison using pgvector embeddings
- Decision deferred until Phase 2

---

## Infrastructure & Local Dev

### Hosting: Railway
- Staging and production run on [Railway](https://railway.com)
- Railway manages PostgreSQL (pgvector template), Redis, object storage buckets, and all application services
- Services auto-deploy from GitHub on merge to `main` (staging) or manual promotion (production)
- See `docs/architecture/deployment.md` for the full Railway setup guide

### Docker + Docker Compose
- Local development runs entirely in Docker Compose: Next.js, FastAPI, PostgreSQL, Redis, MinIO, Celery worker
- Single `docker compose up` to get a full working environment
- No dependency on local Python or Node installations beyond Docker

### Environment Configuration
- All secrets and environment-specific config via environment variables
- `.env` for local dev (gitignored) — copy from `.env.example` at the repo root
- Production secrets managed in Railway's environment variable UI — never in source control

---

## Deferred Technologies

### Temporal
- Deferred to Phase 6 (Automation Agents)
- Will be evaluated for durable multi-step grading workflows, intervention agent orchestration, and retry/recovery guarantees
- If adopted, Celery workers for those specific workflows would be migrated to Temporal activities

---

## What This Stack Is Not

- Not a microservices architecture — monolithic FastAPI backend to start; split only when there is a demonstrated need
- Not serverless — persistent workers and a long-lived database connection pool make serverless a poor fit for the grading pipeline
- Not a real-time push system — polling with React Query is sufficient for batch progress; WebSockets are not in scope unless latency requirements demand it
