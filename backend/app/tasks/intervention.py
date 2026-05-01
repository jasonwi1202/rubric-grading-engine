"""Intervention agent Celery task (M7-01).

The :func:`scan_intervention_signals` task is scheduled via Celery Beat to run
daily.  It scans every teacher's student skill profiles for persistent gaps,
regressions, and non-response patterns, and creates
:class:`~app.models.intervention_recommendation.InterventionRecommendation`
records that surface to teachers for review and approval.

Behaviour:
- Loads all teacher IDs from the ``users`` table (no tenant context — the
  users table does not have RLS).
- For each teacher, activates the RLS tenant context and calls
  :func:`~app.services.intervention_agent.scan_teacher_for_interventions`.
- Errors for individual teachers are logged and skipped so that a failure for
  one teacher does not abort the entire scan.
- The task is idempotent: re-running it always converges to the same DB state
  because the service skips signals that already have a 'pending_review' row.

Security invariants:
- Task accepts no arguments — there is no external input to validate.
- Data access for each teacher is tenant-scoped through the RLS context set by
  :func:`~app.db.session.set_tenant_context` before any tenant-scoped query.
- No student PII is logged — only entity IDs (``teacher_id``).

Test note — ``asyncio`` import
-------------------------------
``asyncio`` is imported at module level so that tests can patch
``app.tasks.intervention.asyncio.run``.  This patches the ``run`` attribute
on the shared ``asyncio`` module object, which also affects the
``run_task_async()`` helper (defined in ``app.db.session``) because both
references point to the same module singleton.  This is the same pattern used
by other task modules.
"""

from __future__ import annotations

import asyncio  # noqa: F401  # preserved for test patch compatibility
import logging

from app.db.session import _TaskSessionLocal, run_task_async, set_tenant_context
from app.tasks.celery_app import celery

logger = logging.getLogger(__name__)
AsyncSessionLocal = _TaskSessionLocal


# ---------------------------------------------------------------------------
# Async implementation helper
# ---------------------------------------------------------------------------


async def _run_scan_intervention_signals() -> None:
    """Async wrapper: load all teacher IDs, scan each teacher's profiles."""
    from app.services.intervention_agent import (  # noqa: PLC0415
        get_all_teacher_ids,
        scan_teacher_for_interventions,
    )

    # Load all teacher IDs without a tenant context (users table has no RLS).
    async with AsyncSessionLocal() as db:
        teacher_ids = await get_all_teacher_ids(db)

    logger.info(
        "Intervention scan started",
        extra={"teacher_count": len(teacher_ids)},
    )

    total_created = 0
    failed_teachers = 0

    for teacher_id in teacher_ids:
        try:
            async with AsyncSessionLocal() as db:
                await set_tenant_context(db, teacher_id)
                created = await scan_teacher_for_interventions(db, teacher_id)
                total_created += len(created)
                if created:
                    logger.info(
                        "Intervention recommendations created for teacher",
                        extra={
                            "teacher_id": str(teacher_id),
                            "count": len(created),
                        },
                    )
        except Exception as exc:  # noqa: BLE001
            failed_teachers += 1
            logger.error(
                "Intervention scan failed for teacher — skipping",
                extra={
                    "teacher_id": str(teacher_id),
                    "error_type": type(exc).__name__,
                },
            )

    logger.info(
        "Intervention scan complete",
        extra={
            "total_recommendations_created": total_created,
            "teachers_scanned": len(teacher_ids),
            "teachers_failed": failed_teachers,
        },
    )


# ---------------------------------------------------------------------------
# Celery task
# ---------------------------------------------------------------------------


@celery.task(  # type: ignore[untyped-decorator]
    name="tasks.intervention.scan_intervention_signals",
    bind=True,
    max_retries=3,
)
def scan_intervention_signals(self: object) -> None:
    """Scan all teacher student profiles for intervention signals.

    Scheduled via Celery Beat (daily at 07:00 UTC).  Detects regression,
    persistent_gap, and non_responder signals from the stored skill profiles
    for every teacher in the system.  Creates
    :class:`~app.models.intervention_recommendation.InterventionRecommendation`
    records for new signals so that teachers can approve or dismiss them from
    the teacher interface.

    The task is idempotent — signals that already have a 'pending_review'
    record are skipped so that repeated runs do not accumulate duplicates.

    No student-facing action is taken by this task.  All consequential actions
    (assigning exercises, sending feedback, etc.) require explicit teacher
    approval via the ``POST /api/v1/interventions/{id}/approve`` endpoint.

    Raises:
        celery.exceptions.Retry: On unexpected infrastructure failures, with
            exponential back-off (``2 ** attempt`` seconds).
        Exception: Re-raised after exhausted retries so Celery marks the task
            as ``FAILURE``.
    """
    try:
        run_task_async(_run_scan_intervention_signals())
    except Exception as exc:
        attempt = self.request.retries  # type: ignore[attr-defined]
        if attempt < self.max_retries:  # type: ignore[attr-defined]
            logger.warning(
                "Intervention scan task failed — will retry",
                extra={
                    "error_type": type(exc).__name__,
                    "attempt": attempt,
                },
            )
            raise self.retry(exc=exc, countdown=2**attempt) from exc  # type: ignore[attr-defined]
        logger.error(
            "Intervention scan task failed — retries exhausted",
            extra={"error_type": type(exc).__name__},
        )
        raise
