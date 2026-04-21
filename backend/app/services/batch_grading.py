"""Batch grading orchestration service.

Handles the three operations introduced by M3.16:

- ``trigger_batch_grading``  — enqueue one Celery grading task per queued
  essay, initialise the Redis progress hash, and transition the assignment
  status to ``grading``.
- ``get_grading_status``     — validate ownership, then read the full
  progress snapshot from Redis (zero Postgres essay-count queries).
- ``retry_essay_grading``    — re-enqueue grading for a single ``queued``
  essay, resetting its Redis progress entry first.

Security invariants:
- Every function accepts ``teacher_id`` and passes it through to every
  query so no cross-teacher access is possible.
- No student PII is logged — only entity IDs appear in log output.
"""

from __future__ import annotations

import logging
import uuid
from typing import TypedDict

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import (
    AssignmentNotGradeableError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
)
from app.models.assignment import Assignment, AssignmentStatus
from app.models.class_ import Class
from app.models.essay import Essay, EssayStatus
from app.models.student import Student
from app.services.assignment import get_assignment
from app.services.grading_progress import (
    BatchProgress,
    get_progress,
    initialize_progress,
    reset_essay_for_retry,
)

logger = logging.getLogger(__name__)


class EssayProgressItem(TypedDict):
    """Per-essay progress item returned by :func:`get_grading_status`."""

    id: str
    status: str
    student_name: str | None
    error: str | None


class GradingStatusData(TypedDict):
    """Return type of :func:`get_grading_status`."""

    status: str
    total: int
    complete: int
    failed: int
    essays: list[EssayProgressItem]


# ---------------------------------------------------------------------------
# Trigger batch grading
# ---------------------------------------------------------------------------


async def trigger_batch_grading(
    db: AsyncSession,
    redis: Redis,  # type: ignore[type-arg]
    assignment_id: uuid.UUID,
    teacher_id: uuid.UUID,
    essay_ids: list[uuid.UUID] | None = None,
    strictness: str = "balanced",
) -> int:
    """Enqueue one grading task per queued essay for an assignment.

    1. Validates assignment ownership and gradeable state.
    2. Loads all ``queued`` essays (or the subset given by *essay_ids*).
    3. Transitions the assignment to ``grading`` (if still ``open``).
    4. Initialises the Redis progress hash.
    5. Enqueues one :func:`~app.tasks.grading.grade_essay` task per essay.

    Args:
        db: Async database session.
        redis: Async Redis client (``decode_responses=True``).
        assignment_id: UUID of the assignment to grade.
        teacher_id: Authenticated teacher's UUID (enforces tenant isolation).
        essay_ids: Optional explicit list of essay UUIDs to grade.  When
            ``None``, all essays with ``status=queued`` are included.
        strictness: Grading strictness — ``"lenient"``, ``"balanced"``, or
            ``"strict"``.

    Returns:
        Number of tasks enqueued.

    Raises:
        NotFoundError: Assignment does not exist.
        ForbiddenError: Assignment belongs to a different teacher.
        AssignmentNotGradeableError: Assignment is not in ``open`` or
            ``grading`` state, or there are no queued essays.
    """
    # 1. Load and validate the assignment (enforces tenant ownership).
    assignment = await get_assignment(db, teacher_id, assignment_id)

    if assignment.status not in (AssignmentStatus.open, AssignmentStatus.grading):
        raise AssignmentNotGradeableError(
            f"Assignment must be in 'open' or 'grading' state to trigger grading. "
            f"Current status: '{assignment.status}'."
        )

    # 2. Load queued essays with optional student name for Redis initialisation.
    query = (
        select(Essay, Student.full_name)
        .outerjoin(Student, Essay.student_id == Student.id)
        .where(
            Essay.assignment_id == assignment_id,
            Essay.status == EssayStatus.queued,
        )
    )
    if essay_ids:
        query = query.where(Essay.id.in_(essay_ids))

    result = await db.execute(query)
    rows = result.all()

    if not rows:
        raise AssignmentNotGradeableError("No essays are queued for grading.")

    # 3. Transition assignment to grading (if still open).
    if assignment.status == AssignmentStatus.open:
        assignment.status = AssignmentStatus.grading
        await db.commit()
        await db.refresh(assignment)

    # 4. Initialise Redis progress (overwrites any previous state).
    essay_pairs: list[tuple[uuid.UUID, str | None]] = [
        (essay.id, student_name) for essay, student_name in rows
    ]
    await initialize_progress(redis, assignment_id, essay_pairs)

    # 5. Enqueue one task per essay.
    from app.tasks.grading import grade_essay  # noqa: PLC0415 — lazy to avoid circular import

    for essay, _ in rows:
        grade_essay.delay(
            str(essay.id),
            str(teacher_id),
            strictness,
            str(assignment_id),
        )

    logger.info(
        "Batch grading triggered",
        extra={
            "assignment_id": str(assignment_id),
            "teacher_id": str(teacher_id),
            "enqueued": len(rows),
        },
    )
    return len(rows)


# ---------------------------------------------------------------------------
# Get grading status
# ---------------------------------------------------------------------------


def _derive_batch_status(progress: BatchProgress) -> str:
    """Derive the overall batch status string from progress counters."""
    done = progress.complete + progress.failed
    if done < progress.total:
        return "processing"
    if progress.failed == 0:
        return "complete"
    if progress.complete == 0:
        return "failed"
    return "partial"


async def get_grading_status(
    db: AsyncSession,
    redis: Redis,  # type: ignore[type-arg]
    assignment_id: uuid.UUID,
    teacher_id: uuid.UUID,
) -> GradingStatusData:
    """Read batch progress from Redis.

    Validates assignment ownership (one lightweight DB query), then reads
    all progress data from Redis — zero Postgres essay-scan queries.

    Returns a :class:`GradingStatusData` dict suitable for validation by
    :class:`~app.schemas.batch_grading.GradingStatusResponse`.

    Raises:
        NotFoundError: Assignment does not exist.
        ForbiddenError: Assignment belongs to a different teacher.
    """
    # Ownership check — required for security even though progress data
    # comes from Redis.
    await get_assignment(db, teacher_id, assignment_id)

    progress = await get_progress(redis, assignment_id)

    if progress is None:
        # Batch not yet started or Redis key expired.
        return GradingStatusData(
            status="idle",
            total=0,
            complete=0,
            failed=0,
            essays=[],
        )

    return GradingStatusData(
        status=_derive_batch_status(progress),
        total=progress.total,
        complete=progress.complete,
        failed=progress.failed,
        essays=[
            EssayProgressItem(
                id=str(ep.essay_id),
                status=ep.status,
                student_name=ep.student_name,
                error=ep.error,
            )
            for ep in progress.essays
        ],
    )


# ---------------------------------------------------------------------------
# Retry a single failed essay
# ---------------------------------------------------------------------------


async def retry_essay_grading(
    db: AsyncSession,
    redis: Redis,  # type: ignore[type-arg]
    essay_id: uuid.UUID,
    teacher_id: uuid.UUID,
    strictness: str = "balanced",
) -> None:
    """Re-enqueue grading for a single failed (reverted-to-queued) essay.

    Failed essays are reverted to ``queued`` status by the Celery task after
    retries are exhausted.  This endpoint allows the teacher to re-trigger
    grading for such an essay without re-grading the entire batch.

    Args:
        db: Async database session.
        redis: Async Redis client.
        essay_id: UUID of the essay to re-grade.
        teacher_id: Authenticated teacher's UUID.
        strictness: Grading strictness — ``"lenient"``, ``"balanced"``, or
            ``"strict"``.

    Raises:
        NotFoundError: Essay does not exist.
        ForbiddenError: Essay belongs to a different teacher.
        ConflictError: Essay is already being graded or has already been
            graded (status is not ``queued``).
    """
    # Load essay — single tenant-scoped query.
    essay_result = await db.execute(
        select(Essay)
        .join(Assignment, Essay.assignment_id == Assignment.id)
        .join(Class, Assignment.class_id == Class.id)
        .where(
            Essay.id == essay_id,
            Class.teacher_id == teacher_id,
        )
    )
    essay = essay_result.scalar_one_or_none()

    if essay is None:
        # Distinguish 404 from 403.
        exists = await db.execute(select(Essay.id).where(Essay.id == essay_id))
        if exists.scalar_one_or_none() is None:
            raise NotFoundError("Essay not found.")
        raise ForbiddenError("You do not have access to this essay.")

    if essay.status == EssayStatus.grading:
        raise ConflictError("This essay is already being graded.")

    if essay.status != EssayStatus.queued:
        raise ConflictError(f"Only queued essays can be retried. Current status: '{essay.status}'.")

    assignment_id = essay.assignment_id

    # Reset Redis progress entry so the batch counters remain accurate.
    await reset_essay_for_retry(redis, assignment_id, essay_id)

    # Re-enqueue the grading task.
    from app.tasks.grading import grade_essay  # noqa: PLC0415 — lazy to avoid circular import

    grade_essay.delay(
        str(essay_id),
        str(teacher_id),
        strictness,
        str(assignment_id),
    )

    logger.info(
        "Essay grading retry enqueued",
        extra={
            "essay_id": str(essay_id),
            "assignment_id": str(assignment_id),
            "teacher_id": str(teacher_id),
        },
    )
