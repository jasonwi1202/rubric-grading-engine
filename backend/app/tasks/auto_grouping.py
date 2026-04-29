"""Auto-grouping Celery task (M6-01).

The :func:`compute_class_groups` task is enqueued whenever a teacher locks a
grade.  It re-clusters the students of the affected class into skill-gap groups
based on their current :class:`~app.models.student_skill_profile.StudentSkillProfile`
data, and atomically replaces the class's
:class:`~app.models.student_group.StudentGroup` rows.

Behaviour:
- Resolves the ``class_id`` from the provided ``grade_id`` (via the
  Essay → Assignment → Class join), fully tenant-scoped via ``teacher_id``.
- Skips gracefully if the grade or class cannot be found or if the teacher
  does not own them.
- Delegates all grouping logic to
  :func:`~app.services.auto_grouping.compute_and_persist_groups`.
- Idempotent: re-running with the same arguments recomputes from the current
  skill profiles and overwrites the stored groups, always converging to the
  same result for a given set of inputs.
- Retry-safe: the DELETE → INSERT inside the service runs in a single
  transaction, so a crash mid-execution leaves the database in the pre-task
  state and the retry can proceed safely.

Security invariants:
- Task accepts only UUID strings — no full entity objects.
- Data access is tenant-scoped through ``teacher_id`` in every query.
- No student PII is logged — only entity IDs.

Test note — ``asyncio`` import
-------------------------------
``asyncio`` is imported at module level so that tests can patch
``app.tasks.auto_grouping.asyncio.run``.  This patches the ``run`` attribute
on the shared ``asyncio`` module object, which also affects the
``run_task_async()`` helper (defined in ``app.db.session``) because both
references point to the same module singleton.  This is the same pattern used
by ``app.tasks.skill_profile``.
"""

from __future__ import annotations

import asyncio  # noqa: F401  # preserved for test patch compatibility
import logging
import uuid
from typing import cast

from app.db.session import _TaskSessionLocal, run_task_async, set_tenant_context
from app.exceptions import ForbiddenError, NotFoundError
from app.tasks.celery_app import celery

logger = logging.getLogger(__name__)
AsyncSessionLocal = _TaskSessionLocal


# ---------------------------------------------------------------------------
# Async implementation helpers
# ---------------------------------------------------------------------------


async def _get_class_id_for_grade(
    grade_id: uuid.UUID,
    teacher_id: uuid.UUID,
) -> uuid.UUID:
    """Return the class_id for the class that owns *grade_id*.

    The query is fully tenant-scoped (joins through Class.teacher_id) so a
    spoofed grade_id cannot expose another teacher's data.

    Note: with FORCE ROW LEVEL SECURITY enabled on the ``grades`` table (see
    migration ``20260424_020_rls_enable_tenant_isolation``), a follow-up
    existence check against the same session cannot distinguish a missing grade
    from a cross-tenant grade — the RLS policy hides both identically.  Any
    missing or cross-tenant grade is therefore surfaced as ``NotFoundError``.

    Raises:
        NotFoundError: Grade not found or belongs to a different teacher.
    """
    from sqlalchemy import select  # noqa: PLC0415

    from app.models.assignment import Assignment  # noqa: PLC0415
    from app.models.class_ import Class  # noqa: PLC0415
    from app.models.essay import Essay, EssayVersion  # noqa: PLC0415
    from app.models.grade import Grade  # noqa: PLC0415

    async with AsyncSessionLocal() as db:
        await set_tenant_context(db, teacher_id)
        row = await db.execute(
            select(Class.id.label("class_id"))
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
            raise NotFoundError("Grade not found.")

    return cast(uuid.UUID, result.class_id)


async def _run_compute_class_groups(
    grade_id: str,
    teacher_id: str,
) -> None:
    """Async wrapper: resolve class, compute groups, persist result."""
    from app.config import settings  # noqa: PLC0415
    from app.services.auto_grouping import (  # noqa: PLC0415
        compute_and_persist_groups,
    )

    grade_uuid = uuid.UUID(grade_id)
    teacher_uuid = uuid.UUID(teacher_id)

    class_id = await _get_class_id_for_grade(grade_uuid, teacher_uuid)

    async with AsyncSessionLocal() as db:
        await set_tenant_context(db, teacher_uuid)
        await compute_and_persist_groups(
            db=db,
            teacher_id=teacher_uuid,
            class_id=class_id,
            underperformance_threshold=settings.auto_grouping_underperformance_threshold,
            min_group_size=settings.auto_grouping_min_group_size,
        )

    logger.info(
        "Auto-grouping task complete",
        extra={
            "grade_id": grade_id,
            "class_id": str(class_id),
            "teacher_id": teacher_id,
        },
    )


# ---------------------------------------------------------------------------
# Celery task
# ---------------------------------------------------------------------------


@celery.task(  # type: ignore[untyped-decorator]
    name="tasks.auto_grouping.compute_class_groups",
    bind=True,
    max_retries=3,
)
def compute_class_groups(
    self: object,
    grade_id: str,
    teacher_id: str,
) -> None:
    """Compute and persist skill-gap student groups for the class that owns *grade_id*.

    Triggered on grade lock events.  Reads all enrolled students' skill
    profiles for the class, clusters by shared underperforming skill
    dimensions, enforces the minimum group size, and atomically replaces the
    class's StudentGroup rows.

    The task is idempotent — safe to re-run with the same arguments because
    ``compute_and_persist_groups`` always recomputes from the current profiles
    and the DELETE → INSERT is transactional.

    Args:
        grade_id:   UUID string of the :class:`~app.models.grade.Grade` whose
                    lock event triggered this task.  Used to resolve the class.
        teacher_id: UUID string of the owning teacher.  Used for tenant
                    isolation in every database query.

    Raises:
        celery.exceptions.Retry: On transient database errors, with
            exponential back-off (``2 ** attempt`` seconds).
        Exception: Re-raised after exhausted retries so Celery marks the task
            as ``FAILURE``.
    """
    try:
        run_task_async(_run_compute_class_groups(grade_id, teacher_id))
    except (NotFoundError, ForbiddenError) as exc:
        logger.warning(
            "Auto-grouping task skipped — grade not found or access denied",
            extra={"grade_id": grade_id, "error_type": type(exc).__name__},
        )
        # Do not retry: there is no correct state to converge to.
    except Exception as exc:
        attempt = self.request.retries  # type: ignore[attr-defined]
        if attempt < self.max_retries:  # type: ignore[attr-defined]
            logger.warning(
                "Auto-grouping task failed — will retry",
                extra={
                    "grade_id": grade_id,
                    "error_type": type(exc).__name__,
                    "attempt": attempt,
                },
            )
            raise self.retry(exc=exc, countdown=2**attempt) from exc  # type: ignore[attr-defined]
        logger.error(
            "Auto-grouping task failed — retries exhausted",
            extra={"grade_id": grade_id, "error_type": type(exc).__name__},
        )
        raise
