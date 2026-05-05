"""FastAPI application factory.

This module creates the FastAPI app instance, registers global exception
handlers, and mounts all API routers.  Import the ``app`` object from here
when starting the server::

    uvicorn app.main:app --host 0.0.0.0 --port 8000
"""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.exceptions import (
    ConflictError,
    ForbiddenError,
    LLMError,
    LLMParseError,
    NotFoundError,
    RateLimitError,
    RubricGradingError,
    UnauthorizedError,
    ValidationError,
)

logger = logging.getLogger(__name__)

# Map framework HTTP status codes to documented error codes from the API catalog.
# Only codes present in docs/architecture/api-design.md#error-codes are used so
# the frontend's error.code branching logic is always consistent.
_HTTP_STATUS_TO_ERROR_CODE: dict[int, str] = {
    400: "VALIDATION_ERROR",
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "VALIDATION_ERROR",
    409: "CONFLICT",
    422: "VALIDATION_ERROR",
    429: "RATE_LIMITED",
}

# Stable public messages for domain exceptions. These are intentionally static
# so user-controlled exception content never leaks to API clients.
_DOMAIN_ERROR_MESSAGES: dict[type[RubricGradingError], str] = {
    NotFoundError: "Resource not found.",
    UnauthorizedError: "Authentication required.",
    ForbiddenError: "You do not have access to this resource.",
    ConflictError: "Request conflicts with current resource state.",
    RateLimitError: "Too many requests. Please try again later.",
    ValidationError: "Request validation failed.",
}

# Static message mapping for framework-raised HTTP errors.
_HTTP_STATUS_TO_PUBLIC_MESSAGE: dict[int, str] = {
    400: "Request validation failed.",
    401: "Authentication required.",
    403: "You do not have access to this resource.",
    404: "Resource not found.",
    405: "Method not allowed.",
    409: "Request conflicts with current resource state.",
    422: "Request validation failed.",
    429: "Too many requests. Please try again later.",
}


@asynccontextmanager
async def _lifespan(application: FastAPI) -> AsyncGenerator[None, None]:
    """Manage resources that must be initialised once and cleaned up on shutdown."""
    yield
    # Graceful shutdown: close the Redis client used by RateLimitMiddleware.
    redis_client = getattr(application.state, "rate_limit_redis", None)
    if redis_client is not None:
        await redis_client.aclose()


def create_app() -> FastAPI:
    """Construct and configure the FastAPI application."""
    from app.config import settings
    from app.logging_config import configure_logging

    configure_logging(settings.log_level)

    application = FastAPI(
        title="Rubric Grading Engine",
        version="0.1.0",
        docs_url="/api/v1/docs",
        redoc_url="/api/v1/redoc",
        openapi_url="/api/v1/openapi.json",
        lifespan=_lifespan,
    )

    _register_exception_handlers(application)
    _register_middleware(application)
    _register_routers(application)

    return application


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------


def _register_middleware(application: FastAPI) -> None:
    from redis.asyncio import Redis

    from app.config import settings
    from app.middleware import (
        CorrelationIdMiddleware,
        RateLimitMiddleware,
        RequestMetricsMiddleware,
        SecurityHeadersMiddleware,
    )

    # Create a single Redis client for rate limiting.  Stored in app.state so
    # the lifespan handler can call aclose() on graceful shutdown, preventing
    # leaked connections in long-running processes and test teardown.
    redis_client: Redis[str] = Redis.from_url(settings.redis_url, decode_responses=True)
    application.state.rate_limit_redis = redis_client

    # Middleware registration order for FastAPI/Starlette (LIFO execution):
    # add_middleware() inserts at the *front* of the middleware stack, so the
    # last call here is the *outermost* middleware (runs first on a request,
    # last on a response).
    #
    # Desired request flow:  CorrelationId → SecurityHeaders → CORS → RateLimit → Metrics → App
    # Desired response flow: App → Metrics → RateLimit → CORS → SecurityHeaders → CorrelationId
    #
    # This ensures:
    #   - Correlation IDs are available to ALL downstream middleware and route
    #     handlers so that every log line during a request carries the ID.
    #   - Security headers appear on ALL responses, including CORS preflight
    #     responses (OPTIONS).  CORSMiddleware can short-circuit and return a
    #     preflight response without calling the inner app; if SecurityHeaders
    #     were inside CORS it would be skipped on those responses.
    #   - CORS preflight and credentialed-request handling runs before the
    #     rate-limit layer so that OPTIONS never counts against the limit.
    #   - Rate-limit 429s are returned before the route handler is invoked.
    #   - RequestMetrics wraps the innermost app so that latency measurements
    #     reflect only application processing time, not middleware overhead.

    # 1. Request metrics — innermost (added first); captures application latency only.
    application.add_middleware(RequestMetricsMiddleware)

    # 2. Rate limiting — sits just outside metrics so that rate-limited 429s
    #    are still measured and their latency is recorded.
    application.add_middleware(RateLimitMiddleware, redis_client=redis_client)

    # 3. CORS — sits between RateLimit and SecurityHeaders so it handles
    #    preflight and adds Access-Control-* headers before SecurityHeaders
    #    wraps the final response.
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Correlation-Id"],
        expose_headers=["X-Correlation-Id"],
    )

    # 4. Security headers — wraps CORS so headers are applied to every
    #    response, including CORS preflight 200s and rate-limit 429s.
    application.add_middleware(SecurityHeadersMiddleware)

    # 5. Correlation ID — outermost (added last); runs first on a request so
    #    that correlation_id_var is set before any other middleware or handler
    #    emits log lines.
    application.add_middleware(CorrelationIdMiddleware)


# ---------------------------------------------------------------------------
# Exception handlers
# ---------------------------------------------------------------------------


def _error_response(
    status_code: int,
    code: str,
    message: str,
    field: str | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message, "field": field}},
    )


def _register_exception_handlers(application: FastAPI) -> None:
    @application.exception_handler(NotFoundError)
    async def not_found_handler(request: Request, exc: NotFoundError) -> JSONResponse:
        return _error_response(404, exc.code, _DOMAIN_ERROR_MESSAGES[NotFoundError])

    @application.exception_handler(UnauthorizedError)
    async def unauthorized_handler(request: Request, exc: UnauthorizedError) -> JSONResponse:
        return _error_response(401, exc.code, _DOMAIN_ERROR_MESSAGES[UnauthorizedError])

    @application.exception_handler(ForbiddenError)
    async def forbidden_handler(request: Request, exc: ForbiddenError) -> JSONResponse:
        return _error_response(403, exc.code, _DOMAIN_ERROR_MESSAGES[ForbiddenError])

    @application.exception_handler(ConflictError)
    async def conflict_handler(request: Request, exc: ConflictError) -> JSONResponse:
        return _error_response(409, exc.code, _DOMAIN_ERROR_MESSAGES[ConflictError])

    @application.exception_handler(RateLimitError)
    async def rate_limit_handler(request: Request, exc: RateLimitError) -> JSONResponse:
        return _error_response(429, exc.code, _DOMAIN_ERROR_MESSAGES[RateLimitError])

    @application.exception_handler(ValidationError)
    async def domain_validation_handler(request: Request, exc: ValidationError) -> JSONResponse:
        return _error_response(422, exc.code, _DOMAIN_ERROR_MESSAGES[ValidationError], exc.field)

    @application.exception_handler(LLMParseError)
    async def llm_parse_error_handler(request: Request, exc: LLMParseError) -> JSONResponse:
        logger.error(
            "LLM parse error",
            extra={
                "path": request.url.path,
                "error_code": exc.code,
                "error_type": type(exc).__name__,
            },
        )
        return _error_response(500, exc.code, "An unexpected error occurred.")

    @application.exception_handler(LLMError)
    async def llm_error_handler(request: Request, exc: LLMError) -> JSONResponse:
        logger.error(
            "LLM error",
            extra={
                "path": request.url.path,
                "error_code": exc.code,
                "error_type": type(exc).__name__,
            },
        )
        return _error_response(503, exc.code, "LLM service is temporarily unavailable.")

    @application.exception_handler(RubricGradingError)
    async def base_domain_handler(request: Request, exc: RubricGradingError) -> JSONResponse:
        logger.error(
            "Rubric grading error",
            extra={
                "path": request.url.path,
                "error_code": exc.code,
                "error_type": type(exc).__name__,
            },
        )
        return _error_response(500, exc.code, "An unexpected error occurred.")

    @application.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _HTTP_STATUS_TO_ERROR_CODE.get(exc.status_code, "INTERNAL_ERROR")
        if exc.status_code >= 500:
            logger.error(
                "HTTP exception",
                extra={
                    "path": request.url.path,
                    "status_code": exc.status_code,
                    "error_code": code,
                    "error_type": type(exc).__name__,
                },
            )
            message = "An unexpected error occurred."
        else:
            message = _HTTP_STATUS_TO_PUBLIC_MESSAGE.get(
                exc.status_code,
                "An unexpected error occurred.",
            )
        return _error_response(exc.status_code, code, message)

    @application.exception_handler(RequestValidationError)
    async def request_validation_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        first = exc.errors()[0] if exc.errors() else {}
        loc = first.get("loc", ())
        # Strip only the leading location type segment (body, query, path, header, cookie)
        # so a real field named "query" or "path" is preserved further in the tuple.
        _loc_prefixes = {"body", "query", "path", "header", "cookie"}
        loc_parts = [str(p) for p in loc]
        while loc_parts and loc_parts[0] in _loc_prefixes:
            loc_parts = loc_parts[1:]
        field: str | None = ".".join(loc_parts) or None
        message = first.get("msg", "Request validation failed")
        return _error_response(422, "VALIDATION_ERROR", str(message), field)

    @application.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        log_extra = {
            "path": request.url.path,
            "error_type": type(exc).__name__,
        }
        if application.debug:
            logger.exception("Unhandled exception", extra=log_extra)
        else:
            logger.error("Unhandled exception", extra=log_extra)
        return _error_response(500, "INTERNAL_ERROR", "An unexpected error occurred.")


# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------


def _register_routers(application: FastAPI) -> None:
    from app.config import settings  # noqa: PLC0415
    from app.routers.account import router as account_router
    from app.routers.assignments import router as assignments_router
    from app.routers.auth import router as auth_router
    from app.routers.classes import router as classes_router
    from app.routers.comment_bank import router as comment_bank_router
    from app.routers.contact import router as contact_router
    from app.routers.copilot import router as copilot_router
    from app.routers.essays import essay_router
    from app.routers.essays import router as essays_router
    from app.routers.exports import router as exports_router
    from app.routers.grades import essay_grade_router, grades_router
    from app.routers.health import router as health_router
    from app.routers.integrity import (
        assignment_integrity_router,
        essay_integrity_router,
        integrity_reports_router,
    )
    from app.routers.intervention import router as intervention_router
    from app.routers.media_comments import grade_media_router, media_comments_router
    from app.routers.onboarding import router as onboarding_router
    from app.routers.recommendations import router as recommendations_router
    from app.routers.regrade_requests import (
        assignments_regrade_router,
        grades_regrade_router,
        regrade_requests_router,
    )
    from app.routers.rubric_templates import router as rubric_templates_router
    from app.routers.rubrics import router as rubrics_router
    from app.routers.students import router as students_router
    from app.routers.worklist import router as worklist_router

    application.include_router(health_router, prefix="/api/v1")
    application.include_router(contact_router, prefix="/api/v1")
    application.include_router(auth_router, prefix="/api/v1")
    application.include_router(onboarding_router, prefix="/api/v1")
    application.include_router(account_router, prefix="/api/v1")
    application.include_router(rubrics_router, prefix="/api/v1")
    application.include_router(rubric_templates_router, prefix="/api/v1")
    application.include_router(classes_router, prefix="/api/v1")
    application.include_router(students_router, prefix="/api/v1")
    application.include_router(essays_router, prefix="/api/v1")
    application.include_router(essay_router, prefix="/api/v1")
    application.include_router(essay_grade_router, prefix="/api/v1")
    application.include_router(essay_integrity_router, prefix="/api/v1")
    application.include_router(assignment_integrity_router, prefix="/api/v1")
    application.include_router(assignments_router, prefix="/api/v1")
    application.include_router(grades_router, prefix="/api/v1")
    application.include_router(grades_regrade_router, prefix="/api/v1")
    application.include_router(assignments_regrade_router, prefix="/api/v1")
    application.include_router(regrade_requests_router, prefix="/api/v1")
    application.include_router(integrity_reports_router, prefix="/api/v1")
    application.include_router(comment_bank_router, prefix="/api/v1")
    application.include_router(exports_router, prefix="/api/v1")
    application.include_router(grade_media_router, prefix="/api/v1")
    application.include_router(media_comments_router, prefix="/api/v1")
    application.include_router(worklist_router, prefix="/api/v1")
    application.include_router(recommendations_router, prefix="/api/v1")
    application.include_router(intervention_router, prefix="/api/v1")
    application.include_router(copilot_router, prefix="/api/v1")

    # Register the test-only internal router only when export failure injection
    # is enabled.  The config validator already prevents this flag from being
    # set in staging/production, so this router is never reachable in those
    # environments.
    if settings.export_task_force_fail:
        from app.routers.internal import router as internal_router  # noqa: PLC0415

        application.include_router(internal_router, prefix="/api/v1")


# ---------------------------------------------------------------------------
# Application instance
# ---------------------------------------------------------------------------

app = create_app()
