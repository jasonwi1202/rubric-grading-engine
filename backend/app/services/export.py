"""Export service — PDF batch export orchestration.

Handles three operations:

- ``trigger_export``           — validate ownership, store initial Redis record,
                                 enqueue the export Celery task, write audit log,
                                 return the task_id.
- ``get_export_status``        — validate teacher ownership via Redis record,
                                 return current task status.
- ``get_export_download_url``  — validate ownership, check status is complete,
                                 generate a short-lived pre-signed S3 URL,
                                 write audit log, return the URL.

Security invariants:
- teacher_id is stored in the Redis export record and validated on every
  status and download request — cross-teacher access returns ForbiddenError.
- No student PII in any log statement — only entity IDs.
- S3 object keys are never logged or included in exception messages.
"""

from __future__ import annotations

import logging
import uuid
from typing import TypedDict, cast

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import ConflictError, ForbiddenError, NotFoundError
from app.models.audit_log import AuditLog
from app.services.assignment import get_assignment
from app.storage.s3 import generate_presigned_url

logger = logging.getLogger(__name__)

# Redis key prefix for export task records.
_EXPORT_KEY_PREFIX = "export:"

# Export record TTL in Redis: 1 hour.
_EXPORT_TTL_SECONDS = 3600

# Pre-signed S3 URL TTL: 15 minutes (per acceptance criteria).
EXPORT_PRESIGNED_URL_TTL_SECONDS = 900


# ---------------------------------------------------------------------------
# Typed return value
# ---------------------------------------------------------------------------


class ExportStatusData(TypedDict):
    """Return type of :func:`get_export_status`."""

    task_id: str
    status: str
    total: int
    complete: int
    error: str | None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _export_redis_key(task_id: str) -> str:
    return f"{_EXPORT_KEY_PREFIX}{task_id}"


# ---------------------------------------------------------------------------
# Public service functions
# ---------------------------------------------------------------------------


async def trigger_export(
    db: AsyncSession,
    redis: Redis,  # type: ignore[type-arg]
    assignment_id: uuid.UUID,
    teacher_id: uuid.UUID,
) -> str:
    """Validate ownership, enqueue the export task, and return the task_id.

    Args:
        db: Async database session.
        redis: Async Redis client (``decode_responses=True``).
        assignment_id: UUID of the assignment to export.
        teacher_id: Authenticated teacher's UUID (enforces tenant isolation).

    Returns:
        String UUID of the newly created export task.

    Raises:
        NotFoundError: Assignment does not exist.
        ForbiddenError: Assignment belongs to a different teacher.
    """
    # Validate ownership — raises NotFoundError / ForbiddenError as needed.
    await get_assignment(db, teacher_id, assignment_id)

    task_id = str(uuid.uuid4())
    redis_key = _export_redis_key(task_id)

    # Store the initial export record in Redis so status polls can start
    # immediately.  teacher_id is stored here for all subsequent auth checks.
    await redis.hset(
        redis_key,
        mapping={
            "status": "pending",
            "teacher_id": str(teacher_id),
            "assignment_id": str(assignment_id),
            "total": "0",
            "complete": "0",
        },
    )
    await redis.expire(redis_key, _EXPORT_TTL_SECONDS)

    # Write audit log entry — INSERT only, no UPDATE/DELETE on audit_logs.
    # after_value shape matches the catalog in docs/architecture/data-model.md#auditlog.
    audit = AuditLog(
        teacher_id=teacher_id,
        entity_type="export",
        entity_id=assignment_id,
        action="export_requested",
        before_value=None,
        after_value={
            "assignment_id": str(assignment_id),
            "format": "pdf",
            "task_id": task_id,
        },
    )
    db.add(audit)
    await db.commit()

    # Enqueue the Celery export task.  If broker submission fails after the
    # Redis record and audit log have been written, mark the export record as
    # failed so polling clients do not see a permanently pending task.
    from app.tasks.export import export_assignment  # noqa: PLC0415

    try:
        export_assignment.delay(str(assignment_id), str(teacher_id), task_id)
    except Exception as exc:
        try:
            await redis.hset(
                redis_key,
                mapping={"status": "failed", "error": "ENQUEUE_FAILED"},
            )
        except Exception as redis_exc:
            logger.error(
                "Failed to update export status after enqueue failure",
                extra={
                    "assignment_id": str(assignment_id),
                    "teacher_id": str(teacher_id),
                    "task_id": task_id,
                    "error_type": type(redis_exc).__name__,
                },
            )
        logger.error(
            "Failed to enqueue export task",
            extra={
                "assignment_id": str(assignment_id),
                "teacher_id": str(teacher_id),
                "task_id": task_id,
                "error_type": type(exc).__name__,
            },
        )
        raise RuntimeError("Failed to enqueue export task.") from exc

    logger.info(
        "Export task enqueued",
        extra={
            "assignment_id": str(assignment_id),
            "teacher_id": str(teacher_id),
            "task_id": task_id,
        },
    )
    return task_id


async def get_export_status(
    task_id: str,
    teacher_id: uuid.UUID,
    redis: Redis,  # type: ignore[type-arg]
) -> ExportStatusData:
    """Return the current export task status.

    Reads entirely from Redis after verifying teacher ownership.

    Args:
        task_id: Export task UUID string (from the trigger response).
        teacher_id: Authenticated teacher's UUID.
        redis: Async Redis client (``decode_responses=True``).

    Returns:
        :class:`ExportStatusData` dict with status counters.

    Raises:
        NotFoundError: Task not found (expired or never created).
        ForbiddenError: Task belongs to a different teacher.
    """
    redis_key = _export_redis_key(task_id)
    record: dict[str, str] = cast(dict[str, str], await redis.hgetall(redis_key))

    if not record:
        raise NotFoundError("Export task not found.")

    if record.get("teacher_id") != str(teacher_id):
        raise ForbiddenError("You do not have access to this export task.")

    return ExportStatusData(
        task_id=task_id,
        status=record.get("status", "pending"),
        total=int(record.get("total", "0")),
        complete=int(record.get("complete", "0")),
        error=record.get("error"),
    )


async def get_export_download_url(
    db: AsyncSession,
    task_id: str,
    teacher_id: uuid.UUID,
    redis: Redis,  # type: ignore[type-arg]
) -> str:
    """Return a pre-signed S3 URL for the completed export ZIP.

    URL TTL is :data:`EXPORT_PRESIGNED_URL_TTL_SECONDS` (15 minutes).

    Args:
        db: Async database session (used for the audit log entry).
        task_id: Export task UUID string.
        teacher_id: Authenticated teacher's UUID.
        redis: Async Redis client (``decode_responses=True``).

    Returns:
        Pre-signed S3 URL string valid for 15 minutes.

    Raises:
        NotFoundError: Task not found or S3 key missing.
        ForbiddenError: Task belongs to a different teacher.
        ConflictError: Export is not yet complete.
    """
    redis_key = _export_redis_key(task_id)
    record: dict[str, str] = cast(dict[str, str], await redis.hgetall(redis_key))

    if not record:
        raise NotFoundError("Export task not found.")

    if record.get("teacher_id") != str(teacher_id):
        raise ForbiddenError("You do not have access to this export task.")

    status = record.get("status", "pending")
    if status != "complete":
        raise ConflictError(f"Export is not complete. Current status: '{status}'.")

    s3_key = record.get("s3_key")
    if not s3_key:
        raise NotFoundError("Export file not found.")

    url = generate_presigned_url(s3_key, expires_in=EXPORT_PRESIGNED_URL_TTL_SECONDS)

    # Write audit log entry for the download — INSERT only.
    assignment_id_str = record.get("assignment_id", "")
    assignment_uuid: uuid.UUID | None = None
    try:
        assignment_uuid = uuid.UUID(assignment_id_str)
    except ValueError:
        # assignment_id in the Redis record is malformed — log the issue rather
        # than silently masking it with a surrogate UUID.
        logger.error(
            "Export download: assignment_id in Redis record is not a valid UUID",
            extra={"task_id": task_id},
        )

    audit = AuditLog(
        teacher_id=teacher_id,
        entity_type="export",
        entity_id=assignment_uuid,
        action="export_downloaded",
        before_value=None,
        after_value={"task_id": task_id},
    )
    db.add(audit)
    await db.commit()

    logger.info(
        "Export download URL generated",
        extra={"task_id": task_id, "teacher_id": str(teacher_id)},
    )
    return url
