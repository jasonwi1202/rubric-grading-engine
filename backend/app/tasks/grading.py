"""Grading Celery task.

The :func:`grade_essay` task is the core AI grading worker.  It is enqueued
once per essay when a teacher triggers batch grading on an assignment.

Behaviour:
- Calls :func:`app.services.grading.grade_essay` to run the full grading
  pipeline (LLM call → parse → validate → write DB records).
- Handles all LLM failure modes with exponential back-off retries.
- On exhausted retries, reverts the essay status to ``queued`` so the
  teacher can trigger a re-grade, and re-raises so Celery marks the task
  as ``FAILURE``.

Security invariants:
- No essay content is logged at any level.
- Only entity IDs appear in log output.
- Teacher ownership is validated inside the service before any data is read.
"""

from __future__ import annotations

import asyncio
import logging
import uuid

from app.db.session import AsyncSessionLocal
from app.exceptions import LLMError
from app.tasks.celery_app import celery

logger = logging.getLogger(__name__)


async def _run_grade_essay(essay_id: str, teacher_id: str, strictness: str) -> str:
    """Async wrapper: opens a session and calls the grading service.

    Returns the string UUID of the created :class:`Grade` record.
    """
    from app.services.grading import (
        grade_essay,  # noqa: PLC0415 — lazy import to avoid circular deps at module load
    )

    async with AsyncSessionLocal() as db:
        grade = await grade_essay(
            db=db,
            essay_id=uuid.UUID(essay_id),
            teacher_id=uuid.UUID(teacher_id),
            strictness=strictness,
        )
        return str(grade.id)


async def _revert_essay_to_queued(essay_id: str) -> None:
    """Set the essay status back to ``queued`` after exhausted retries.

    This allows the teacher to trigger a re-grade instead of leaving the
    essay stuck in ``grading`` status.
    """
    from sqlalchemy import select  # noqa: PLC0415

    from app.models.essay import Essay, EssayStatus  # noqa: PLC0415

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Essay).where(Essay.id == uuid.UUID(essay_id)))
        essay = result.scalar_one_or_none()
        if essay is not None:
            essay.status = EssayStatus.queued
            await db.commit()


@celery.task(  # type: ignore[untyped-decorator]
    name="tasks.grading.grade_essay",
    bind=True,
    max_retries=3,
)
def grade_essay(self: object, essay_id: str, teacher_id: str, strictness: str) -> str:
    """Grade a single essay against its assignment's rubric snapshot.

    Loads essay data from the database, calls the LLM grading pipeline,
    writes :class:`~app.models.grade.Grade` and
    :class:`~app.models.grade.CriterionScore` records, and updates the essay
    status to ``graded``.

    Args:
        essay_id: UUID string of the :class:`~app.models.essay.Essay` to grade.
            The task always loads fresh data from the database — the payload
            contains only the ID.
        teacher_id: UUID string of the owning teacher.  Used for tenant
            isolation inside the grading service.
        strictness: One of ``"lenient"``, ``"balanced"``, ``"strict"``.

    Returns:
        String UUID of the created :class:`~app.models.grade.Grade` record.

    Raises:
        celery.exceptions.Retry: On LLM transport errors, with exponential
            back-off (``2 ** attempt`` seconds).
        Exception: Re-raised after exhausted retries so Celery marks the
            task as ``FAILURE``.
    """
    try:
        return asyncio.run(_run_grade_essay(essay_id, teacher_id, strictness))
    except LLMError as exc:
        attempt = self.request.retries  # type: ignore[attr-defined]
        if attempt < self.max_retries:  # type: ignore[attr-defined]
            logger.warning(
                "LLM error in grading task — will retry",
                extra={
                    "essay_id": essay_id,
                    "error_type": type(exc).__name__,
                    "attempt": attempt,
                },
            )
            raise self.retry(exc=exc, countdown=2**attempt) from exc  # type: ignore[attr-defined]

        # Exhausted retries — revert essay to queued so it can be re-triggered.
        logger.error(
            "Grading task failed — retries exhausted, reverting essay to queued",
            extra={"essay_id": essay_id, "error_type": type(exc).__name__},
        )
        asyncio.run(_revert_essay_to_queued(essay_id))
        raise

    except Exception as exc:
        logger.error(
            "Grading task failed with unrecoverable error",
            extra={"essay_id": essay_id, "error_type": type(exc).__name__},
        )
        asyncio.run(_revert_essay_to_queued(essay_id))
        raise
