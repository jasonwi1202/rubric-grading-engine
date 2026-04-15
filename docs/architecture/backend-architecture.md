# Backend Architecture

## Overview

The backend is a monolithic FastAPI application with a separate Celery worker process for async task execution. The two processes share the same codebase and database but run independently — FastAPI handles HTTP requests, Celery handles long-running jobs like grading and batch processing.

---

## Process Model

```
┌─────────────────────────────────────────────────────────────┐
│                        Client (Next.js)                     │
└────────────────────────────┬────────────────────────────────┘
                             │ HTTPS / REST
┌────────────────────────────▼────────────────────────────────┐
│                     FastAPI Application                     │
│                                                             │
│  ┌─────────────┐  ┌──────────────┐  ┌───────────────────┐  │
│  │   Routers   │  │   Services   │  │  LLM Client       │  │
│  │  (HTTP API) │→ │ (Business    │→ │  (OpenAI API)     │  │
│  │             │  │  Logic)      │  │                   │  │
│  └─────────────┘  └──────┬───────┘  └───────────────────┘  │
│                          │                                  │
│                  ┌───────▼───────┐                          │
│                  │  Celery       │                          │
│                  │  Task Enqueue │                          │
│                  └───────┬───────┘                          │
└──────────────────────────┼──────────────────────────────────┘
                           │
          ┌────────────────┼────────────────┐
          │                │                │
┌─────────▼──────┐ ┌───────▼──────┐ ┌──────▼───────┐
│   PostgreSQL   │ │    Redis     │ │  S3 Storage  │
│  (App Data +  │ │  (Queue +    │ │  (Files +    │
│   Audit Log)  │ │   Cache)     │ │   Exports)   │
└────────────────┘ └──────────────┘ └──────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│                     Celery Worker(s)                        │
│                                                             │
│  ┌──────────────┐  ┌───────────────┐  ┌─────────────────┐  │
│  │  Grading     │  │  Integrity    │  │  Export / File  │  │
│  │  Tasks       │  │  Check Tasks  │  │  Generation     │  │
│  └──────────────┘  └───────────────┘  └─────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

---

## Directory Structure

```
backend/
├── app/
│   ├── main.py                  # FastAPI app factory, middleware, router registration
│   ├── config.py                # Settings via pydantic-settings (env vars)
│   ├── dependencies.py          # Shared FastAPI dependencies (DB session, auth, etc.)
│   │
│   ├── routers/                 # HTTP route handlers — thin, delegate to services
│   │   ├── assignments.py
│   │   ├── classes.py
│   │   ├── essays.py
│   │   ├── grading.py
│   │   ├── rubrics.py
│   │   ├── students.py
│   │   └── users.py
│   │
│   ├── services/                # Business logic — no HTTP concerns
│   │   ├── grading_service.py
│   │   ├── feedback_service.py
│   │   ├── rubric_service.py
│   │   ├── student_profile_service.py
│   │   ├── integrity_service.py
│   │   └── export_service.py
│   │
│   ├── tasks/                   # Celery task definitions
│   │   ├── celery_app.py        # Celery app instance and configuration
│   │   ├── grading_tasks.py
│   │   ├── integrity_tasks.py
│   │   └── export_tasks.py
│   │
│   ├── llm/                     # LLM client and prompt management
│   │   ├── client.py            # OpenAI API wrapper
│   │   ├── prompts/             # Versioned prompt templates
│   │   │   ├── grading.py
│   │   │   ├── feedback.py
│   │   │   └── instruction.py
│   │   └── parsers.py           # Structured output parsing from LLM responses
│   │
│   ├── models/                  # SQLAlchemy ORM models
│   │   ├── base.py
│   │   ├── user.py
│   │   ├── class_.py
│   │   ├── student.py
│   │   ├── assignment.py
│   │   ├── essay.py
│   │   ├── rubric.py
│   │   ├── grade.py
│   │   └── audit_log.py
│   │
│   ├── schemas/                 # Pydantic request/response schemas
│   │   ├── assignment.py
│   │   ├── essay.py
│   │   ├── grade.py
│   │   └── ...
│   │
│   ├── db/
│   │   ├── session.py           # Async SQLAlchemy session factory
│   │   └── migrations/          # Alembic migrations
│   │
│   └── storage/
│       └── s3.py                # S3 / MinIO client wrapper
│
├── tests/
├── Dockerfile
├── pyproject.toml
└── alembic.ini
```

---

## Layer Responsibilities

### Routers
- Handle HTTP request/response only
- Validate input via Pydantic schemas
- Call into services — no business logic in routers
- Return Pydantic response models
- Handle HTTP-level errors (404, 403, 422)

### Services
- Contain all business logic
- Orchestrate database queries, LLM calls, and task enqueuing
- Are not aware of HTTP — return domain objects or raise domain exceptions
- Are testable without an HTTP context

### Tasks (Celery)
- Handle all long-running operations: grading, integrity checks, export generation
- Accept job parameters (IDs, not full objects) and load data themselves
- Update job progress in Redis
- Write results to Postgres when complete
- Are idempotent where possible

### LLM Client
- Thin wrapper around the OpenAI API
- Handles retries, timeouts, and error normalization
- Accepts a prompt template + context, returns a structured response
- Model name is injected from config — never hardcoded

---

## Authentication & Authorization

- **JWT-based authentication** — tokens issued on login, validated on every request
- Short-lived access tokens (15 min) + refresh tokens (7 days) stored in httpOnly cookies
- Teacher-scoped data access enforced in the service layer — every query is filtered by the authenticated teacher's ID
- No teacher can access another teacher's classes, students, or assignments
- Role checks (teacher vs. admin) enforced via FastAPI dependency injection

---

## Error Handling

- Domain exceptions defined in `app/exceptions.py` (e.g., `EssayNotFoundError`, `RubricWeightInvalidError`) — see `docs/architecture/error-handling.md` for the full exception hierarchy
- Global exception handler in `main.py` maps domain exceptions to HTTP responses
- All unhandled exceptions are logged with full context before returning a generic 500
- LLM failures return a structured error — grading never silently fails

---

## Key Design Constraints

- Routers never import from `tasks/` directly — they call services, and services enqueue tasks
- Services never import from `routers/` — no circular dependencies
- LLM calls only happen in `services/` and `tasks/` — never in routers or models
- All database access uses the async session — no synchronous SQLAlchemy calls
