# Performance

## Overview

This document defines performance targets, identifies the system's known bottlenecks, and specifies the strategies used to meet targets at each layer. Performance is not an afterthought — grading speed is a core product principle. Teachers will abandon a tool that makes them wait.

---

## Performance Targets

| Operation | Target | Notes |
|---|---|---|
| Single essay grading (end-to-end) | < 15 seconds | From trigger to grade available in review queue |
| Batch of 30 essays | < 5 minutes | All essays graded, progress visible in real time |
| Essay review page load | < 1 second | All scores and feedback visible |
| Student profile page load | < 1 second | Skill chart, history, gaps |
| Rubric save | < 500ms | |
| Export (30 PDFs as ZIP) | < 60 seconds | Async — teacher notified on completion |
| Batch grading progress poll | < 200ms response | Reads from Redis, not Postgres |
| Authentication (login) | < 500ms | |

---

## Known Bottlenecks and Mitigations

### 1. LLM API Latency (Biggest Risk)
**Problem:** A single LLM grading call for a ~500-word essay with a 5-criterion rubric takes 5–12 seconds depending on model and load.

**Mitigations:**
- Grading is fully async — teacher triggers it and returns to other work. Progress is shown in real time via polling.
- Batch grading runs essay tasks **in parallel** via multiple Celery workers — a batch of 30 essays with 4 workers takes ~4x less wall-clock time than sequential processing
- `OPENAI_GRADING_MODEL` is configurable — a faster/cheaper model can be used for Phase 1 if latency targets aren't met with GPT-4o
- Streaming responses are not used for grading — structured JSON output is required, which is incompatible with streaming. No streaming for now.
- Set aggressive timeouts (`LLM_REQUEST_TIMEOUT_SECONDS = 60`) — a stalled request should not block a worker indefinitely

### 2. Database Query Performance
**Problem:** Student profile reads, class heatmaps, and analytics queries touch many rows as data accumulates.

**Mitigations:**
- `StudentSkillProfile` stores pre-aggregated skill data as JSONB — profile reads are a single row lookup, not an aggregation query at read time
- Key indexes defined in the data model: `(teacher_id, academic_year)` on Class, `(essay_id)` on Grade, `(grade_id)` on CriterionScore
- Analytics queries (score distributions, common issues) run against a specific assignment — queries are bounded by `assignment_id`, not full-table scans
- Audit log is append-only and indexed by `(entity_type, entity_id)` and `(teacher_id, created_at DESC)` — it does not slow down main entity queries
- PgBouncer connection pooling in production prevents connection exhaustion under concurrent teacher load

### 3. File Extraction Latency
**Problem:** PDF text extraction can be slow for large files.

**Mitigations:**
- Text extraction happens synchronously on upload (before the essay is queued for grading) but is bounded by the `MAX_ESSAY_FILE_SIZE_MB` limit (10MB)
- Extraction for a single essay should complete in < 2 seconds for typical student essays — if it exceeds 5 seconds, something is wrong with the file
- The original file is stored to S3 first, before extraction — if extraction fails, the file is not lost

### 4. Batch Progress Polling
**Problem:** Polling 30 essays' progress every 3 seconds from multiple teacher sessions could create DB load.

**Mitigations:**
- Progress state is stored in Redis (a counter per assignment), not queried from Postgres
- `GET /assignments/{id}/grading-status` reads entirely from Redis — zero DB queries for in-progress status
- Polling stops automatically when status transitions to `complete` or `failed`

### 5. Export Generation
**Problem:** Generating 30 PDFs and zipping them is CPU-intensive.

**Mitigations:**
- Export is always async — never blocks the HTTP response
- Export worker runs as a separate Celery queue (lower priority than grading tasks)
- Pre-signed S3 URL is returned for download — file is never streamed through FastAPI

---

## Caching Strategy

| Data | Cache Location | TTL | Invalidation |
|---|---|---|---|
| Grading batch progress | Redis | 1 hour | Overwritten on each task completion; deleted when batch completes |
| Teacher session | Redis (via JWT) | 15 min (access), 7 days (refresh) | Explicit logout or expiry |
| Export download URL | Redis | 1 hour | TTL expiry |
| Student skill profile | PostgreSQL (denormalized JSONB) | No TTL — updated on grade lock | Upserted by Celery task after lock |

**What is NOT cached:**
- Individual essay grades — always read from Postgres (too critical to serve stale data)
- Rubric definitions — small, fast to query, must always be current
- Audit logs — correctness over speed

---

## Scaling Considerations

### Celery Workers
- Workers are stateless and horizontally scalable — add more worker containers to increase grading throughput
- Separate worker queues for grading vs. export vs. background jobs — grading is always highest priority
- At 4 workers, a class of 30 essays grades in ~4 minutes. At 8 workers, ~2 minutes.

### Database
- Start with a single Postgres instance — read replicas are not needed until teacher volume is significant
- When read replicas are added, route analytics and profile queries to the replica; writes and grading results to primary

### Application Server
- FastAPI is async throughout — a single FastAPI instance handles many concurrent requests efficiently
- Horizontal scaling is straightforward (stateless app server, all state in Postgres/Redis)

---

## Performance Monitoring

Track these metrics from day one:

| Metric | Alert Threshold | Notes |
|---|---|---|
| LLM API p95 latency | > 20 seconds | Per grading task |
| LLM API error rate | > 5% | Over any 5-minute window |
| Grading task failure rate | > 2% | Over any hour |
| API p95 response time | > 2 seconds | For non-grading endpoints |
| Celery queue depth | > 200 tasks | Indicates workers are falling behind |
| Postgres connection pool saturation | > 80% | Approaching exhaustion |
| Redis memory usage | > 75% | |

Use structured logging (JSON) from FastAPI and Celery workers so logs are queryable. Correlate grading task IDs across logs using a shared `job_id` field.
