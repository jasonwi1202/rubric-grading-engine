"""Celery application instance.

Creates and configures the Celery app using broker and result backend URLs
from application settings.  Import this module to access the ``celery``
singleton::

    from app.tasks.celery_app import celery

The worker is started with::

    celery -A app.tasks.celery_app worker --loglevel=info

Correlation ID propagation
--------------------------
Every task message carries the current ``correlation_id`` from the FastAPI
request context (set by ``CorrelationIdMiddleware``) in its Celery headers.
Workers restore the ID from the headers before the task function runs so that
all log lines emitted during the task carry the same ID as the originating
HTTP request.

Signals used:

- ``before_task_publish`` — embeds the correlation ID into the outgoing task
  message headers (runs in the publisher — FastAPI or another task).
- ``task_prerun`` — restores the correlation ID from task headers in the
  worker process before the task body executes.
- ``task_postrun`` — clears the correlation ID after the task finishes to
  prevent stale IDs from leaking into the next task on the same worker thread.
"""

import logging

from celery import Celery
from celery.schedules import crontab
from celery.signals import before_task_publish, task_postrun, task_prerun, worker_init

from app.config import settings
from app.logging_config import configure_logging, correlation_id_var

logger = logging.getLogger(__name__)

celery = Celery(
    "rubric_grading_engine",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.tasks.debug", "app.tasks.email", "app.tasks.grading", "app.tasks.export", "app.tasks.embedding"],
)

celery.conf.update(
    # Serialization
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    # Timezone
    timezone="UTC",
    enable_utc=True,
    # Worker concurrency comes from settings
    worker_concurrency=settings.celery_worker_concurrency,
    # Global default time limits for all tasks; individual tasks may override these
    task_soft_time_limit=settings.grading_task_soft_time_limit,
    task_time_limit=settings.grading_task_hard_time_limit,
    # Do not store successful task results indefinitely
    result_expires=settings.celery_result_expires_seconds,
    # ---------------------------------------------------------------------------
    # Celery Beat schedule
    # ---------------------------------------------------------------------------
    # Scan for expiring trials once per day at 06:00 UTC.  Running after
    # midnight avoids edge cases around DST transitions and ensures the
    # day-0 window (trial_ends_at == today) is fully within the UTC day.
    beat_schedule={
        "scan-trial-expirations-daily": {
            "task": "tasks.email.scan_trial_expirations",
            "schedule": crontab(hour=6, minute=0),
        },
    },
)


# ---------------------------------------------------------------------------
# Correlation ID propagation via Celery signals
# ---------------------------------------------------------------------------


@worker_init.connect  # type: ignore[untyped-decorator]  # Celery signal stubs are incomplete
def _configure_worker_logging(**_kwargs: object) -> None:
    """Configure structured JSON logging when the Celery worker process starts.

    Using the ``worker_init`` signal (rather than module-level code) ensures
    that this runs only in the worker process, not in the FastAPI process that
    imports this module.  The FastAPI process configures logging in
    ``create_app()`` via ``configure_logging(settings.log_level)``.
    """
    configure_logging(settings.log_level)


@before_task_publish.connect  # type: ignore[untyped-decorator]  # Celery signal stubs are incomplete
def _inject_correlation_id(headers: dict[str, object], **_kwargs: object) -> None:
    """Embed the current correlation ID in outgoing task message headers.

    Called in the *publisher* (FastAPI worker or another Celery task) just
    before the task message is sent to the broker.  The value comes from
    ``correlation_id_var``, which is set by ``CorrelationIdMiddleware`` for
    HTTP requests or by ``_restore_correlation_id`` for nested tasks.
    """
    cid = correlation_id_var.get("")
    if cid:
        headers["correlation_id"] = cid


@task_prerun.connect  # type: ignore[untyped-decorator]  # Celery signal stubs are incomplete
def _restore_correlation_id(task: object, **_kwargs: object) -> None:
    """Restore the correlation ID from task headers before the task body runs.

    Called in the *Celery worker process* before the task function executes.
    Sets ``correlation_id_var`` so that all log lines emitted during the task
    (including those in services called by the task) carry the same ID as the
    originating HTTP request.

    Note: ``asyncio.run()`` (used by sync Celery tasks that wrap async code)
    copies the current thread's ContextVar context, so the value set here is
    visible inside the coroutine run by ``asyncio.run()``.
    """
    try:
        request = getattr(task, "request", None)
        cid = ""
        if request is not None:
            # Celery 5 stores custom headers under request.headers.
            hdrs = getattr(request, "headers", None) or {}
            cid = hdrs.get("correlation_id", "") or ""
        correlation_id_var.set(cid)
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "Failed to restore correlation_id from task headers — using empty string",
            extra={"error_type": type(exc).__name__},
        )
        correlation_id_var.set("")


@task_postrun.connect  # type: ignore[untyped-decorator]  # Celery signal stubs are incomplete
def _clear_correlation_id(**_kwargs: object) -> None:
    """Clear the correlation ID after the task finishes.

    Prevents stale correlation IDs from leaking into subsequent tasks handled
    by the same worker thread (Celery prefork workers reuse OS threads across
    tasks within the same process lifetime).
    """
    correlation_id_var.set("")
