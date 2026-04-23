"""Exports router — export status and download endpoints.

All endpoints require a valid JWT (``get_current_teacher`` dependency).
No student PII is collected or logged here.

Endpoints:
  GET  /exports/{taskId}/status   — poll export task progress
  GET  /exports/{taskId}/download — get pre-signed S3 URL for completed ZIP
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from redis.asyncio import Redis

from app.db.session import AsyncSession, get_db
from app.dependencies import get_current_teacher
from app.models.user import User
from app.schemas.export import ExportDownloadResponse, ExportStatusResponse
from app.services.export import (
    EXPORT_PRESIGNED_URL_TTL_SECONDS,
    get_export_download_url,
    get_export_status,
)

router = APIRouter(prefix="/exports", tags=["exports"])


# ---------------------------------------------------------------------------
# Redis dependency — same pattern as assignments router
# ---------------------------------------------------------------------------


async def _get_redis() -> AsyncGenerator[Redis, None]:  # type: ignore[type-arg]
    """FastAPI dependency that yields an async Redis client."""
    from app.config import settings

    client: Redis = Redis.from_url(settings.redis_url, decode_responses=True)  # type: ignore[type-arg]
    try:
        yield client
    finally:
        await client.aclose()  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# GET /exports/{taskId}/status
# ---------------------------------------------------------------------------


@router.get(
    "/{task_id}/status",
    summary="Poll export task progress",
)
async def get_export_status_endpoint(
    task_id: str,
    teacher: User = Depends(get_current_teacher),
    redis_client: Redis = Depends(_get_redis),  # type: ignore[type-arg]
) -> JSONResponse:
    """Return the current status of an export task.

    Reads entirely from Redis after verifying teacher ownership.

    Response shape::

        {
          "data": {
            "task_id": "...",
            "status": "pending|processing|complete|failed",
            "total": 30,
            "complete": 12,
            "error": null
          }
        }

    Returns 403 if the task belongs to a different teacher.
    Returns 404 if the task is not found (expired or never created).
    """
    status_data = await get_export_status(
        task_id=task_id,
        teacher_id=teacher.id,
        redis=redis_client,
    )
    response = ExportStatusResponse.model_validate(status_data)
    return JSONResponse(
        status_code=200,
        content={"data": response.model_dump(mode="json")},
    )


# ---------------------------------------------------------------------------
# GET /exports/{taskId}/download
# ---------------------------------------------------------------------------


@router.get(
    "/{task_id}/download",
    summary="Get pre-signed S3 download URL for a completed export",
)
async def get_export_download_endpoint(
    task_id: str,
    teacher: User = Depends(get_current_teacher),
    db: AsyncSession = Depends(get_db),
    redis_client: Redis = Depends(_get_redis),  # type: ignore[type-arg]
) -> JSONResponse:
    """Return a pre-signed S3 URL for the completed export ZIP.

    The URL is valid for 15 minutes.  The teacher downloads the file
    directly from S3 — it is never streamed through FastAPI.

    Response shape::

        {
          "data": {
            "url": "https://...",
            "expires_in_seconds": 900
          }
        }

    Returns 403 if the task belongs to a different teacher.
    Returns 404 if the task is not found.
    Returns 409 if the export is not yet complete.
    """
    url = await get_export_download_url(
        db=db,
        task_id=task_id,
        teacher_id=teacher.id,
        redis=redis_client,
    )
    response = ExportDownloadResponse(
        url=url,
        expires_in_seconds=EXPORT_PRESIGNED_URL_TTL_SECONDS,
    )
    return JSONResponse(
        status_code=200,
        content={"data": response.model_dump(mode="json")},
    )
