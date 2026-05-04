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
- All endpoints require a valid JWT Bearer token (``get_current_teacher``).
  This prevents unauthenticated requests from arming the failure flag and
  ensures only legitimate test users can manipulate the injection state.
- The failure flag is scoped per-assignment (keyed by assignment_id) so
  parallel Playwright workers cannot consume each other's flags.
- No student PII is handled by these endpoints.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Body, Depends
from fastapi.responses import JSONResponse
from redis.asyncio import Redis

from app.dependencies import get_current_teacher
from app.tasks.export import _export_force_fail_once_key

if TYPE_CHECKING:
    from app.models.user import User

# TTL for the armed flag: 5 minutes.  Long enough for a Playwright test to
# trigger the export after arming; short enough not to affect other test runs.
_ARM_TTL_SECONDS = 300

router = APIRouter(prefix="/internal", tags=["internal"])


# ---------------------------------------------------------------------------
# Redis dependency
# ---------------------------------------------------------------------------


async def _get_redis() -> AsyncGenerator[Redis, None]:  # type: ignore[type-arg]  # redis-py Redis is not generic at runtime; Redis[str] raises TypeError
    """FastAPI dependency that yields an async Redis client."""
    from app.config import settings  # noqa: PLC0415

    client: Redis = Redis.from_url(settings.redis_url, decode_responses=True)  # type: ignore[type-arg]  # Redis is not generic at runtime
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
    assignment_id: Annotated[str, Body(embed=True, description="Assignment UUID to target")],
    redis_client: Redis = Depends(_get_redis),  # type: ignore[type-arg]  # Redis is not generic at runtime
    _teacher: User = Depends(get_current_teacher),
) -> JSONResponse:
    """Set a per-assignment one-shot Redis flag that causes the next export task
    for the given assignment to fail.

    The flag is atomically consumed by the first export task that runs for this
    assignment after this call.  Subsequent export tasks proceed normally.
    Scoping the flag to an assignment_id means parallel Playwright workers
    arming different assignments cannot consume each other's flags.

    Used by E2E tests to exercise the failure → retry → success flow
    without a permanent configuration change.

    Request body::

        {"assignment_id": "<UUID>"}

    Response shape::

        {"data": {"armed": true, "assignment_id": "<UUID>"}}

    This endpoint is only available when ``EXPORT_TASK_FORCE_FAIL=true``.
    Requires a valid JWT Bearer token.
    """
    key = _export_force_fail_once_key(assignment_id)
    await redis_client.set(key, "1", ex=_ARM_TTL_SECONDS)
    return JSONResponse(
        status_code=200, content={"data": {"armed": True, "assignment_id": assignment_id}}
    )


# ---------------------------------------------------------------------------
# DELETE /internal/export-test-controls/arm-failure
# ---------------------------------------------------------------------------


@router.delete(
    "/export-test-controls/arm-failure",
    summary="Disarm the one-shot export task failure injection (test-only)",
)
async def disarm_export_failure(
    assignment_id: Annotated[str, Body(embed=True, description="Assignment UUID to disarm")],
    redis_client: Redis = Depends(_get_redis),  # type: ignore[type-arg]  # Redis is not generic at runtime
    _teacher: User = Depends(get_current_teacher),
) -> JSONResponse:
    """Clear the per-assignment one-shot export failure flag without consuming
    it via a task.

    Useful for test teardown if a test is aborted before the flag is consumed.

    Request body::

        {"assignment_id": "<UUID>"}

    Response shape::

        {"data": {"armed": false, "assignment_id": "<UUID>"}}

    This endpoint is only available when ``EXPORT_TASK_FORCE_FAIL=true``.
    Requires a valid JWT Bearer token.
    """
    key = _export_force_fail_once_key(assignment_id)
    await redis_client.delete(key)
    return JSONResponse(
        status_code=200, content={"data": {"armed": False, "assignment_id": assignment_id}}
    )
