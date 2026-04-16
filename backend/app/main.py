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

from app.exceptions import (
    ConflictError,
    ForbiddenError,
    LLMError,
    NotFoundError,
    RubricGradingError,
    ValidationError,
)

logger = logging.getLogger(__name__)


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

    @application.exception_handler(LLMError)
    async def llm_error_handler(request: Request, exc: LLMError) -> JSONResponse:
        return _error_response(503, exc.code, str(exc))

    @application.exception_handler(RubricGradingError)
    async def base_domain_handler(request: Request, exc: RubricGradingError) -> JSONResponse:
        return _error_response(500, exc.code, str(exc))

    @application.exception_handler(RequestValidationError)
    async def request_validation_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        first = exc.errors()[0] if exc.errors() else {}
        field: str | None = ".".join(str(p) for p in first.get("loc", [])) or None
        message = first.get("msg", "Request validation failed")
        return _error_response(422, "VALIDATION_ERROR", str(message), field)

    @application.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.error(
            "Unhandled exception",
            exc_info=exc,
            extra={"path": request.url.path},
        )
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
