"""Internal test-only router.

This router is ONLY registered when ``settings.export_task_force_fail`` is
``True``, which is itself blocked in staging and production by a config
validator.  It provides deterministic failure injection controls for E2E tests.

Endpoints:
  POST   /internal/export-test-controls/arm-failure    — arm one-shot failure
  DELETE /internal/export-test-controls/arm-failure    — disarm (clear) flag

Security:
- These endpoints are unreachable in production/staging because the router is
  never included in the application when ``EXPORT_TASK_FORCE_FAIL=False``.
- No student PII is handled by these endpoints.
- No authentication is required; the endpoints manipulate only a transient
  Redis flag used exclusively in E2E test environments.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from redis.asyncio import Redis

# One-shot force-fail key — must match the constant in app.tasks.export.
_EXPORT_FORCE_FAIL_ONCE_KEY = "export:force_fail_once"

# TTL for the armed flag: 5 minutes.  Long enough for a Playwright test to
# trigger the export after arming; short enough not to affect other test runs.
_ARM_TTL_SECONDS = 300

router = APIRouter(prefix="/internal", tags=["internal"])


# ---------------------------------------------------------------------------
# Redis dependency
# ---------------------------------------------------------------------------


async def _get_redis() -> AsyncGenerator[Redis[str], None]:
    """FastAPI dependency that yields an async Redis client."""
    from app.config import settings  # noqa: PLC0415

    client: Redis[str] = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        yield client
    finally:
        await client.aclose()  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# POST /internal/export-test-controls/arm-failure
# ---------------------------------------------------------------------------


@router.post(
    "/export-test-controls/arm-failure",
    summary="Arm one-shot export task failure injection (test-only)",
)
async def arm_export_failure(
    redis_client: Redis[str] = Depends(_get_redis),
) -> JSONResponse:
    """Set a one-shot Redis flag that causes the next export task to fail.

    The flag is atomically consumed by the first export task that runs after
    this call.  Subsequent export tasks proceed normally.

    Used by E2E tests to exercise the failure → retry → success flow
    without a permanent configuration change.

    Response shape::

        {"data": {"armed": true}}

    This endpoint is only available when ``EXPORT_TASK_FORCE_FAIL=true``.
    """
    await redis_client.set(_EXPORT_FORCE_FAIL_ONCE_KEY, "1", ex=_ARM_TTL_SECONDS)
    return JSONResponse(status_code=200, content={"data": {"armed": True}})


# ---------------------------------------------------------------------------
# DELETE /internal/export-test-controls/arm-failure
# ---------------------------------------------------------------------------


@router.delete(
    "/export-test-controls/arm-failure",
    summary="Disarm the one-shot export task failure injection (test-only)",
)
async def disarm_export_failure(
    redis_client: Redis[str] = Depends(_get_redis),
) -> JSONResponse:
    """Clear the one-shot export failure flag without consuming it via a task.

    Useful for test teardown if a test is aborted before the flag is consumed.

    Response shape::

        {"data": {"armed": false}}

    This endpoint is only available when ``EXPORT_TASK_FORCE_FAIL=true``.
    """
    await redis_client.delete(_EXPORT_FORCE_FAIL_ONCE_KEY)
    return JSONResponse(status_code=200, content={"data": {"armed": False}})
