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
from celery.signals import (
    before_task_publish,
    task_postrun,
    task_prerun,
    worker_init,
    worker_process_init,
)

from app.config import settings
from app.logging_config import configure_logging, correlation_id_var

logger = logging.getLogger(__name__)

celery = Celery(
    "rubric_grading_engine",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=[
        "app.tasks.debug",
        "app.tasks.email",
        "app.tasks.grading",
        "app.tasks.export",
        "app.tasks.embedding",
        "app.tasks.skill_profile",
    ],
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


@worker_process_init.connect  # type: ignore[untyped-decorator]  # Celery signal stubs are incomplete
def _reset_sqlalchemy_pool_after_fork(**_kwargs: object) -> None:
    """Replace the inherited engine and session factory in each prefork child.

    Celery prefork workers inherit the parent's asyncpg connections via fork.
    Those connections are tied to the parent's event loop and produce
    "another operation is in progress" errors when reused in a child.

    Fix: abandon (not close) the inherited pool connections using
    ``close=False`` — closing inherited asyncpg sockets from a forked child
    is unsafe — then create a fresh engine and session factory so every task
    in this child starts with a clean pool.
    """
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    from app.config import settings
    from app.db import session as session_module

    # Do NOT call engine.dispose() here — closing the inherited asyncpg
    # sockets from within a forked child is unsafe (they belong to the
    # parent's event loop).  Simply replace the module-level references so
    # all subsequent task code uses a new, uncontaminated engine.
    # The old engine object will be garbage-collected once no references remain.

    # Create a fresh engine bound to this child's (future) event loop.
    new_engine = create_async_engine(
        settings.database_url,
        poolclass=NullPool,
        echo=False,
    )
    session_module.engine = new_engine
    new_session_factory = async_sessionmaker(
        bind=new_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )
    session_module.AsyncSessionLocal = new_session_factory

    # Patch the already-imported module-level names in task modules so they use
    # the new session factory rather than the parent's captured binding.  Task
    # modules do `from app.db.session import AsyncSessionLocal` at import time,
    # so replacing session_module.AsyncSessionLocal alone is not enough.
    import app.tasks.embedding as _embedding_module  # noqa: PLC0415
    import app.tasks.grading as _grading_module  # noqa: PLC0415
    import app.tasks.skill_profile as _skill_profile_module  # noqa: PLC0415

    _grading_module.AsyncSessionLocal = new_session_factory
    _embedding_module.AsyncSessionLocal = new_session_factory
    _skill_profile_module.AsyncSessionLocal = new_session_factory


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
