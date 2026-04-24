# Error Handling

## Overview

This document defines the error handling strategy for the Rubric Grading Engine — the exception types raised by the service layer, how routers map them to HTTP responses, how Celery tasks surface failures, and what the frontend should do with each category. The goal is consistent, predictable error behavior across every code path.

---

## Error Envelope

Every API error response uses this shape:

```json
{
  "error": {
    "code": "GRADE_LOCKED",
    "message": "This grade has been locked and cannot be edited.",
    "field": null
  }
}
```

- `code` — `SCREAMING_SNAKE_CASE` string. The frontend branches on this, not `message`. Full catalog in [`api-design.md#error-codes`](api-design.md#error-codes).
- `message` — Human-readable description. May change between releases — do not parse it.
- `field` — Present only on validation errors (`VALIDATION_ERROR`). Names the offending request field.

**No student PII in error messages.** Exception messages and API error responses must never include student names, essay content, scores, or other education records. Use entity IDs only.

---

## Domain Exceptions (Service Layer)

Services raise typed domain exceptions. Routers catch them and convert to HTTP responses. Services must never raise `HTTPException` or reference HTTP status codes.

All exceptions live in `backend/app/exceptions.py`:

```python
class RubricGradingError(Exception):
    """Base class for all domain exceptions."""
    code: str = "INTERNAL_ERROR"

class NotFoundError(RubricGradingError):
    """Resource does not exist.

    Use this only when the requested resource truly does not exist. Do not use
    it for authorization or tenant-isolation failures; cross-tenant access
    attempts must raise ``ForbiddenError`` instead.
    """
    code = "NOT_FOUND"

class ForbiddenError(RubricGradingError):
    """Authenticated teacher does not have access to this resource.

    This includes cross-tenant access attempts where the resource exists but
    does not belong to the authenticated teacher.
    """
    code = "FORBIDDEN"

class ConflictError(RubricGradingError):
    """Operation conflicts with current resource state."""
    # Subclasses set specific codes: GRADE_LOCKED, GRADING_IN_PROGRESS, etc.
    code = "CONFLICT"

class ValidationError(RubricGradingError):
    """Input failed domain-level validation (not Pydantic schema validation)."""
    code = "VALIDATION_ERROR"

class LLMError(RubricGradingError):
    """LLM call failed or returned an unparseable response."""
    code = "LLM_UNAVAILABLE"

class LLMParseError(LLMError):
    """LLM response failed schema validation after retries."""
    code = "LLM_PARSE_ERROR"
```

### Specific Conflict and Validation Subclasses

```python
class GradeLockedError(ConflictError):
    code = "GRADE_LOCKED"

class GradingInProgressError(ConflictError):
    code = "GRADING_IN_PROGRESS"

class AssignmentNotGradeableError(ConflictError):
    code = "ASSIGNMENT_NOT_GRADEABLE"

class RubricInUseError(ConflictError):
    code = "RUBRIC_IN_USE"

class RubricWeightInvalidError(ValidationError):
    code = "RUBRIC_WEIGHT_INVALID"

class FileTooLargeError(ValidationError):
    code = "FILE_TOO_LARGE"

class FileTypeNotAllowedError(ValidationError):
    code = "FILE_TYPE_NOT_ALLOWED"
```

---

## Router Exception Handlers

A global exception handler in `app/main.py` maps domain exceptions to HTTP responses:

```python
@app.exception_handler(NotFoundError)
async def not_found_handler(request, exc):
    return JSONResponse(status_code=404, content={"error": {"code": exc.code, "message": str(exc), "field": None}})

@app.exception_handler(ForbiddenError)
async def forbidden_handler(request, exc):
    return JSONResponse(status_code=403, content={"error": {"code": exc.code, "message": str(exc), "field": None}})

@app.exception_handler(ConflictError)
async def conflict_handler(request, exc):
    return JSONResponse(status_code=409, content={"error": {"code": exc.code, "message": str(exc), "field": None}})

@app.exception_handler(ValidationError)
async def domain_validation_handler(request, exc):
    return JSONResponse(status_code=422, content={"error": {"code": exc.code, "message": str(exc), "field": getattr(exc, "field", None)}})

@app.exception_handler(LLMError)
async def llm_error_handler(request, exc):
    # Return a generic message — exc message may contain internal context.
    logger.error("LLM error", extra={"error_code": exc.code, "error_type": type(exc).__name__})
    return JSONResponse(status_code=503, content={"error": {"code": exc.code, "message": "LLM service is temporarily unavailable.", "field": None}})
```

Pydantic's built-in `RequestValidationError` (schema validation) is also intercepted to normalize it into the same envelope with `code: "VALIDATION_ERROR"`.

---

## Celery Task Error Handling

Tasks must not silently swallow exceptions. Every task failure must write a visible error state to the affected entity.

### Grading Task Failure Pattern

```python
@celery_app.task(bind=True, max_retries=3, default_retry_delay=10)
async def grade_essay_task(self, essay_id: str, assignment_id: str, teacher_id: str):
    try:
        await grading_service.grade_essay(essay_id, assignment_id, teacher_id)
    except LLMError as exc:
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc, countdown=2 ** self.request.retries)
        # Exhausted retries — write permanent failure state
        await essay_service.mark_grading_failed(essay_id, error_code="LLM_UNAVAILABLE")
    except Exception as exc:
        await essay_service.mark_grading_failed(essay_id, error_code="INTERNAL_ERROR")
        logger.error("Grading task failed", essay_id=essay_id, error_type=type(exc).__name__)
        raise  # Re-raise so Celery marks task as FAILURE
```

### Task Error Surface

Task failures are surfaced via `GET /assignments/{id}/grading-status`:

```json
{
  "data": {
    "status": "processing",
    "total": 30,
    "complete": 12,
    "failed": 1,
    "essays": [
      { "id": "uuid", "status": "failed", "error": "LLM_UNAVAILABLE" }
    ]
  }
}
```

The `error` field on each essay entry is the `error_code` written during task failure — the same codes from the catalog. The frontend displays these with a retry option.

---

## Logging Rules

Errors are logged with structured fields. These rules are non-negotiable:

- **Never log student PII.** Use entity IDs only: `essay_id`, `student_id`, `grade_id`.
- **Never log LLM response content.** It may contain essay text.
- **Log `error_type=type(exc).__name__`**, not `error=str(exc)` — exception messages can contain PII from upstream.
- **Log at `ERROR` level** for unexpected failures. `WARNING` for expected retries.

```python
# Correct
logger.error("Grading task failed", essay_id=essay_id, error_type=type(exc).__name__)

# Wrong — str(exc) may contain essay content or student name
logger.error("Grading task failed", error=str(exc))
```

---

## Structured JSON Logging

All services (API and Celery workers) emit structured JSON log lines via `app.logging_config`. Every log line includes the following fixed fields:

| Field | Type | Description |
|---|---|---|
| `timestamp` | ISO-8601 UTC | e.g. `"2025-01-15T14:32:01.123Z"` |
| `level` | string | Python level name (`INFO`, `WARNING`, `ERROR`, …) |
| `logger` | string | Dotted logger name (e.g. `app.services.grading`) |
| `service` | string | Always `"rubric-grading-engine"` |
| `correlation_id` | string | Per-request UUID (empty string outside a request) |
| `message` | string | Formatted log message |

Additional fields from `extra=` keyword arguments are merged into the object. Only entity IDs (`essay_id`, `grade_id`, etc.) and operational metadata should appear there — **never student names, essay content, or scores**.

Exception type (`error_type`) is included when an exception is present, but **exception messages and tracebacks are never emitted** — they can contain student PII from database error messages or LLM response fragments.

---

## Correlation IDs

A correlation ID is a UUID4 generated (or echoed from `X-Correlation-Id` request header) by `CorrelationIdMiddleware` for every HTTP request. It is:

- Stored in `app.logging_config.correlation_id_var` (a `ContextVar`) for the request lifetime.
- Included in all log lines emitted during the request via `CorrelationIdFilter`.
- Echoed in the `X-Correlation-Id` response header.
- Propagated to Celery tasks via the task message headers (`before_task_publish` signal) and restored in the worker (`task_prerun` signal) so that background task log lines carry the same ID as the originating HTTP request.

---

## Health Check Endpoint

`GET /api/v1/health` returns dependency reachability status. No authentication is required (used by load balancers and Railway probes).

**Response shape (HTTP 200 — all healthy):**

```json
{
  "status": "ok",
  "service": "rubric-grading-engine-api",
  "version": "0.1.0",
  "dependencies": {
    "database": "ok",
    "redis": "ok"
  }
}
```

**Response shape (HTTP 503 — one or more dependencies unavailable):**

```json
{
  "status": "degraded",
  "service": "rubric-grading-engine-api",
  "version": "0.1.0",
  "dependencies": {
    "database": "unavailable",
    "redis": "ok"
  }
}
```

The response body is always present regardless of status code. Clients should parse it to determine which specific dependency is unhealthy.

---

## Frontend Error Handling

The frontend should:

1. **Always branch on `error.code`**, not HTTP status or `error.message`
2. **Show user-friendly messages** — never render raw `error.message` from the API
3. **Handle retry-able errors** (`LLM_UNAVAILABLE`, `GRADING_IN_PROGRESS`) with a retry action, not just an error state
4. **Handle locked state** (`GRADE_LOCKED`) by refreshing the grade and re-rendering as read-only
5. **Log unexpected codes** to the console in development — production should swallow them gracefully

```typescript
// In a React Query mutation's onError:
function handleGradeError(error: ApiError) {
  switch (error.code) {
    case "GRADE_LOCKED":
      queryClient.invalidateQueries(["grade", gradeId]);
      toast.error("This grade was locked. Refreshing...");
      break;
    case "LLM_UNAVAILABLE":
      toast.error("Grading service is temporarily unavailable. Please try again.");
      break;
    case "FORBIDDEN":
      router.push("/dashboard"); // should not happen — indicates a routing bug
      break;
    default:
      toast.error("Something went wrong. Please try again.");
  }
}
```

Reference: [`api-design.md#error-codes`](api-design.md#error-codes), [`security.md#5-ferpa-compliance`](security.md#5-ferpa-compliance)
