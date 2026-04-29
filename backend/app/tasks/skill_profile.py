"""Skill profile update Celery task (M5-03).

The :func:`update_skill_profile` task is enqueued whenever a teacher locks a
grade.  It recalculates the student's aggregated skill profile from every
locked criterion score across all their assignments and upserts the result
into :class:`~app.models.student_skill_profile.StudentSkillProfile`.

Behaviour:
- Loads the locked :class:`~app.models.grade.Grade` to resolve the student
  whose profile needs updating.
- Skips gracefully if the essay has no student assignment (``student_id`` is
  ``None``) — this is a normal edge case for unassigned essays.
- Delegates all aggregation to
  :func:`~app.services.student_skill_profile.compute_and_upsert_skill_profile`.
- The task is idempotent: re-running it with the same arguments converges to
  the same result because ``compute_and_upsert_skill_profile`` performs a
  full recomputation from locked grades and the upsert is idempotent.

Security invariants:
- Task accepts only UUID strings — no full entity objects.  Data is loaded
  fresh from the database on every run so retries always use current state.
- Data access is tenant-scoped through ``teacher_id``.  A separate unscoped
  existence check is used only to distinguish 404 from 403 — it never returns
  tenant data.
- No student PII (names, essay content, scores) is logged — only entity IDs.
"""

from __future__ import annotations

import asyncio  # noqa: F401  # preserved for test patch compatibility
import logging
import uuid
from typing import cast

from app.db.session import _TaskSessionLocal, run_task_async
from app.exceptions import ForbiddenError, NotFoundError
from app.tasks.celery_app import celery

logger = logging.getLogger(__name__)
AsyncSessionLocal = _TaskSessionLocal


# ---------------------------------------------------------------------------
# Async implementation helpers
# ---------------------------------------------------------------------------


async def _get_student_id_for_grade(
    grade_id: uuid.UUID,
    teacher_id: uuid.UUID,
) -> uuid.UUID | None:
    """Return the student_id for the essay associated with *grade_id*.

    The query is fully tenant-scoped (joins through Class.teacher_id) so a
    task payload with a spoofed grade_id cannot access another teacher's data.

    Returns:
        The student UUID, or ``None`` if the essay has not been assigned to a
        student yet.

    Raises:
        NotFoundError:  Grade not found.
        ForbiddenError: Grade exists but belongs to a different teacher.
    """
    from sqlalchemy import select  # noqa: PLC0415

    from app.models.assignment import Assignment  # noqa: PLC0415
    from app.models.class_ import Class  # noqa: PLC0415
    from app.models.essay import Essay, EssayVersion  # noqa: PLC0415
    from app.models.grade import Grade  # noqa: PLC0415

    async with AsyncSessionLocal() as db:
        row = await db.execute(
            select(Essay.student_id)
            .select_from(Grade)
            .join(EssayVersion, Grade.essay_version_id == EssayVersion.id)
            .join(Essay, EssayVersion.essay_id == Essay.id)
            .join(Assignment, Essay.assignment_id == Assignment.id)
            .join(Class, Assignment.class_id == Class.id)
            .where(
                Grade.id == grade_id,
                Class.teacher_id == teacher_id,
            )
        )
        result = row.one_or_none()

        if result is None:
            # Distinguish 404 from 403 without leaking another teacher's data.
            # Reuse the same session to avoid a second connection.
            exists_row = await db.execute(select(Grade.id).where(Grade.id == grade_id))
            if exists_row.scalar_one_or_none() is None:
                raise NotFoundError("Grade not found.")
            raise ForbiddenError("You do not have access to this grade.")

    return cast(uuid.UUID | None, result.student_id)


async def _run_update_skill_profile(
    grade_id: str,
    teacher_id: str,
) -> None:
    """Async wrapper: resolve student, recompute profile, upsert result."""
    from app.services.student_skill_profile import (  # noqa: PLC0415
        compute_and_upsert_skill_profile,
    )

    grade_uuid = uuid.UUID(grade_id)
    teacher_uuid = uuid.UUID(teacher_id)

    student_id = await _get_student_id_for_grade(grade_uuid, teacher_uuid)
    if student_id is None:
        # Essay has not been assigned to a student — nothing to update.
        logger.info(
            "Skill profile update skipped — essay has no student assignment",
            extra={"grade_id": grade_id, "teacher_id": teacher_id},
        )
        return

    async with AsyncSessionLocal() as db:
        await compute_and_upsert_skill_profile(
            db=db,
            teacher_id=teacher_uuid,
            student_id=student_id,
        )

    logger.info(
        "Skill profile update complete",
        extra={
            "grade_id": grade_id,
            "student_id": str(student_id),
            "teacher_id": teacher_id,
        },
    )


# ---------------------------------------------------------------------------
# Celery task
# ---------------------------------------------------------------------------


@celery.task(  # type: ignore[untyped-decorator]
    name="tasks.skill_profile.update_skill_profile",
    bind=True,
    max_retries=3,
)
def update_skill_profile(
    self: object,
    grade_id: str,
    teacher_id: str,
) -> None:
    """Recompute and upsert the skill profile for the student who owns *grade_id*.

    Triggered on grade lock events.  Loads all locked criterion scores for the
    student from the database, normalises them to canonical skill dimensions,
    computes a recency-weighted average / trend / data-point count per skill,
    and upserts the result into ``StudentSkillProfile``.

    The task is idempotent — safe to re-run if a worker crashes mid-execution
    because the upsert always recomputes from the full set of locked grades.

    Args:
        grade_id:   UUID string of the :class:`~app.models.grade.Grade` whose
                    lock event triggered this task.  Used to resolve the student.
        teacher_id: UUID string of the owning teacher.  Used for tenant
                    isolation in every database query.

    Raises:
        celery.exceptions.Retry: On transient database or dependency errors,
            with exponential back-off (``2 ** attempt`` seconds).
        Exception: Re-raised after exhausted retries so Celery marks the task
            as ``FAILURE``.
    """
    try:
        run_task_async(_run_update_skill_profile(grade_id, teacher_id))
    except (NotFoundError, ForbiddenError) as exc:
        # Grade deleted or belongs to a different teacher — nothing to update.
        logger.warning(
            "Skill profile task skipped — grade not found or access denied",
            extra={"grade_id": grade_id, "error_type": type(exc).__name__},
        )
        # Do not re-raise: there is no correct state to converge to, and
        # retrying would produce the same outcome.
    except Exception as exc:
        attempt = self.request.retries  # type: ignore[attr-defined]
        if attempt < self.max_retries:  # type: ignore[attr-defined]
            logger.warning(
                "Skill profile task failed — will retry",
                extra={
                    "grade_id": grade_id,
                    "error_type": type(exc).__name__,
                    "attempt": attempt,
                },
            )
            raise self.retry(exc=exc, countdown=2**attempt) from exc  # type: ignore[attr-defined]
        logger.error(
            "Skill profile task failed — retries exhausted",
            extra={"grade_id": grade_id, "error_type": type(exc).__name__},
        )
        raise
