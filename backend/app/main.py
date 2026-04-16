"""FastAPI application factory.

This module creates the FastAPI app instance, registers global exception
handlers, and mounts all API routers.  Import the ``app`` object from here
when starting the server::

    uvicorn app.main:app --host 0.0.0.0 --port 8000
"""

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.exceptions import (
    ConflictError,
    ForbiddenError,
    LLMError,
    LLMParseError,
    NotFoundError,
    RubricGradingError,
    ValidationError,
)

logger = logging.getLogger(__name__)

# Map framework HTTP status codes to structured error codes.
_HTTP_STATUS_TO_ERROR_CODE: dict[int, str] = {
    400: "BAD_REQUEST",
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    409: "CONFLICT",
    422: "VALIDATION_ERROR",
}


def create_app() -> FastAPI:
    """Construct and configure the FastAPI application."""
    application = FastAPI(
        title="Rubric Grading Engine",
        version="0.1.0",
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
    )

    _register_exception_handlers(application)
    _register_routers(application)

    return application


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
        return _error_response(404, exc.code, str(exc))

    @application.exception_handler(ForbiddenError)
    async def forbidden_handler(request: Request, exc: ForbiddenError) -> JSONResponse:
        return _error_response(403, exc.code, str(exc))

    @application.exception_handler(ConflictError)
    async def conflict_handler(request: Request, exc: ConflictError) -> JSONResponse:
        return _error_response(409, exc.code, str(exc))

    @application.exception_handler(ValidationError)
    async def domain_validation_handler(request: Request, exc: ValidationError) -> JSONResponse:
        return _error_response(422, exc.code, str(exc), exc.field)

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
        code = _HTTP_STATUS_TO_ERROR_CODE.get(
            exc.status_code,
            "INTERNAL_ERROR" if exc.status_code >= 500 else "ERROR",
        )
        # exc.detail is set by the framework (e.g. "Not Found") and is safe to surface.
        message = str(exc.detail) if exc.detail else "An unexpected error occurred."
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
    from app.routers.health import router as health_router

    application.include_router(health_router, prefix="/api/v1")


# ---------------------------------------------------------------------------
# Application instance
# ---------------------------------------------------------------------------

app = create_app()
