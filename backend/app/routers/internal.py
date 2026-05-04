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
- Ownership of the ``assignment_id`` is verified against the authenticated
  teacher via ``get_assignment`` before any Redis write.  A teacher cannot arm
  failure for another teacher's assignment (returns 403/404).
- ``assignment_id`` is parsed as ``uuid.UUID`` by FastAPI, which normalises the
  value to lowercase hyphenated form before it is used as a Redis key.  This
  guarantees the key produced here matches the one consumed by ``_run_export``.
- The failure flag is scoped per-assignment (keyed by assignment_id) so
  parallel Playwright workers cannot consume each other's flags.
- No student PII is handled by these endpoints.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Body, Depends
from fastapi.responses import JSONResponse
from redis.asyncio import Redis

from app.db.session import AsyncSession, get_db
from app.dependencies import get_current_teacher
from app.services.assignment import get_assignment
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
    assignment_id: Annotated[uuid.UUID, Body(embed=True, description="Assignment UUID to target")],
    db: AsyncSession = Depends(get_db),
    redis_client: Redis = Depends(_get_redis),  # type: ignore[type-arg]  # Redis is not generic at runtime
    teacher: User = Depends(get_current_teacher),
) -> JSONResponse:
    """Set a per-assignment one-shot Redis flag that causes the next export task
    for the given assignment to fail.

    Ownership of ``assignment_id`` is verified against the authenticated teacher
    via ``get_assignment`` before any Redis write.  Raises ``NotFoundError``
    (→ 404) if the assignment does not exist, ``ForbiddenError`` (→ 403) if it
    belongs to a different teacher.

    ``assignment_id`` is accepted as ``uuid.UUID`` so FastAPI normalises it to
    lowercase hyphenated form.  This guarantees the Redis key matches the one
    consumed by ``_run_export`` regardless of how the caller formats the UUID.

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
    await get_assignment(db, teacher.id, assignment_id)
    canonical_id = str(assignment_id)
    key = _export_force_fail_once_key(canonical_id)
    await redis_client.set(key, "1", ex=_ARM_TTL_SECONDS)
    return JSONResponse(
        status_code=200, content={"data": {"armed": True, "assignment_id": canonical_id}}
    )


# ---------------------------------------------------------------------------
# DELETE /internal/export-test-controls/arm-failure
# ---------------------------------------------------------------------------


@router.delete(
    "/export-test-controls/arm-failure",
    summary="Disarm the one-shot export task failure injection (test-only)",
)
async def disarm_export_failure(
    assignment_id: Annotated[uuid.UUID, Body(embed=True, description="Assignment UUID to disarm")],
    db: AsyncSession = Depends(get_db),
    redis_client: Redis = Depends(_get_redis),  # type: ignore[type-arg]  # Redis is not generic at runtime
    teacher: User = Depends(get_current_teacher),
) -> JSONResponse:
    """Clear the per-assignment one-shot export failure flag without consuming
    it via a task.

    Ownership of ``assignment_id`` is verified against the authenticated teacher
    before the key is cleared — a teacher cannot disarm another teacher's flag.

    Useful for test teardown if a test is aborted before the flag is consumed.

    Request body::

        {"assignment_id": "<UUID>"}

    Response shape::

        {"data": {"armed": false, "assignment_id": "<UUID>"}}

    This endpoint is only available when ``EXPORT_TASK_FORCE_FAIL=true``.
    Requires a valid JWT Bearer token.
    """
    await get_assignment(db, teacher.id, assignment_id)
    canonical_id = str(assignment_id)
    key = _export_force_fail_once_key(canonical_id)
    await redis_client.delete(key)
    return JSONResponse(
        status_code=200, content={"data": {"armed": False, "assignment_id": canonical_id}}
    )
