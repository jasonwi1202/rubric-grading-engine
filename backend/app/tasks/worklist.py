"""Worklist generation Celery task (M6-04).

The :func:`refresh_teacher_worklist` task is enqueued whenever a teacher
locks a grade.  It recomputes the full ranked worklist for the teacher from
their students' current skill profiles, persistent group memberships,
per-assignment score sequences, and resubmission data, then atomically
replaces all active worklist items in the database.

Behaviour:
- Accepts ``(grade_id, teacher_id)`` for consistency with the skill-profile
  and auto-grouping tasks.  ``grade_id`` is used only for logging context;
  the actual computation is teacher-scoped (all students, all classes).
- Delegates all worklist logic to
  :func:`~app.services.worklist.compute_and_persist_worklist`.
- Safe to rerun: the service function performs a DELETE → INSERT in a single
  transaction, so retries converge to the current state without duplicates.
- Skips gracefully if the grade or teacher cannot be found or if the teacher
  does not own the grade.

Security invariants:
- Task accepts only UUID strings — no full entity objects.
- Data access is tenant-scoped through ``teacher_id`` in every query.
- No student PII is logged — only entity IDs.

Test note — ``asyncio`` import
-------------------------------
``asyncio`` is imported at module level so that tests can patch
``app.tasks.worklist.asyncio.run``.  This patches the ``run`` attribute
on the shared ``asyncio`` module object, which also affects the
``run_task_async()`` helper (defined in ``app.db.session``) because both
references point to the same module singleton.  This is the same pattern
used by ``app.tasks.skill_profile`` and ``app.tasks.auto_grouping``.
"""

from __future__ import annotations

import asyncio  # noqa: F401  # preserved for test patch compatibility
import logging
import uuid

from app.db.session import _TaskSessionLocal, run_task_async, set_tenant_context
from app.exceptions import ForbiddenError, NotFoundError
from app.tasks.celery_app import celery

logger = logging.getLogger(__name__)
AsyncSessionLocal = _TaskSessionLocal


# ---------------------------------------------------------------------------
# Async implementation helper
# ---------------------------------------------------------------------------


async def _run_refresh_teacher_worklist(
    grade_id: str,
    teacher_id: str,
) -> None:
    """Async wrapper: recompute and persist the teacher worklist."""
    from app.services.worklist import compute_and_persist_worklist  # noqa: PLC0415

    teacher_uuid = uuid.UUID(teacher_id)

    async with AsyncSessionLocal() as db:
        await set_tenant_context(db, teacher_uuid)
        await compute_and_persist_worklist(db=db, teacher_id=teacher_uuid)

    logger.info(
        "Worklist refresh task complete",
        extra={
            "grade_id": grade_id,
            "teacher_id": teacher_id,
        },
    )


# ---------------------------------------------------------------------------
# Celery task
# ---------------------------------------------------------------------------


@celery.task(  # type: ignore[untyped-decorator]
    name="tasks.worklist.refresh_teacher_worklist",
    bind=True,
    max_retries=3,
)
def refresh_teacher_worklist(
    self: object,
    grade_id: str,
    teacher_id: str,
) -> None:
    """Recompute and persist the ranked worklist for the teacher who owns *grade_id*.

    Triggered on grade lock events.  Loads all student skill profiles,
    persistent group memberships, per-assignment score sequences, and
    resubmission data for the teacher, applies the four trigger checks
    (regression, non_responder, persistent_gap, high_inconsistency), ranks
    by urgency, and atomically replaces the teacher's active worklist items.

    The task is idempotent — safe to re-run with the same arguments because
    ``compute_and_persist_worklist`` always deletes existing active items and
    recomputes from the current state within a single transaction.

    Args:
        grade_id:   UUID string of the :class:`~app.models.grade.Grade` whose
                    lock event triggered this task.  Used for logging context only.
        teacher_id: UUID string of the owning teacher.  All worklist computation
                    is scoped to this teacher.

    Raises:
        celery.exceptions.Retry: On transient database errors, with
            exponential back-off (``2 ** attempt`` seconds).
        Exception: Re-raised after exhausted retries so Celery marks the task
            as ``FAILURE``.
    """
    try:
        run_task_async(_run_refresh_teacher_worklist(grade_id, teacher_id))
    except (NotFoundError, ForbiddenError) as exc:
        logger.warning(
            "Worklist refresh task skipped — grade not found or access denied",
            extra={"grade_id": grade_id, "error_type": type(exc).__name__},
        )
        # Do not retry: there is no correct state to converge to.
    except Exception as exc:
        attempt = self.request.retries  # type: ignore[attr-defined]
        if attempt < self.max_retries:  # type: ignore[attr-defined]
            logger.warning(
                "Worklist refresh task failed — will retry",
                extra={
                    "grade_id": grade_id,
                    "error_type": type(exc).__name__,
                    "attempt": attempt,
                },
            )
            raise self.retry(exc=exc, countdown=2**attempt) from exc  # type: ignore[attr-defined]
        logger.error(
            "Worklist refresh task failed — retries exhausted",
            extra={"grade_id": grade_id, "error_type": type(exc).__name__},
        )
        raise
