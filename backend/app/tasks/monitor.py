"""Celery queue monitoring task.

Publishes structured ``celery.queue_depth`` log events once per minute (driven
by Celery Beat).  These events are the primary signal for queue-depth alerting
and capacity planning.

Each event records the number of pending (unprocessed) tasks in a Celery
queue.  When queue depth stays above the alert threshold for more than five
minutes it indicates that workers are falling behind — either a worker crashed
or the grading load has exceeded current worker capacity.

Queues monitored
----------------
- ``celery``   — Default queue; used for grading tasks, skill-profile updates,
                 auto-grouping, worklist generation, and all other tasks unless
                 they specify a dedicated queue.

The event is always emitted, even when depth is zero, so that log-based alert
rules can distinguish "no data" from "zero depth".

Security
--------
No student PII, essay content, S3 keys, or grade data is included in any log
line emitted by this module.  Only integer queue depths and queue names are
recorded.
"""

from __future__ import annotations

import logging

from app.tasks.celery_app import celery

logger = logging.getLogger(__name__)

# Celery's default queue name when no explicit queue is declared on a task.
_DEFAULT_QUEUE = "celery"

# All queues to sample.  Extend this list when dedicated queues are introduced
# (e.g. a separate high-priority grading queue or an export queue).
_MONITORED_QUEUES: tuple[str, ...] = (_DEFAULT_QUEUE,)


@celery.task(name="tasks.monitor.report_queue_metrics")  # type: ignore[untyped-decorator]  # celery stubs are incomplete
def report_queue_metrics() -> dict[str, int]:
    """Emit ``celery.queue_depth`` structured log events for every monitored queue.

    Reads the queue length directly from the Celery broker (Redis) by
    opening a short-lived Redis connection to ``settings.celery_broker_url``.
    Each queue depth is emitted as an individual log event rather than a
    single aggregated event so that log-aggregator alert rules can filter on
    a single field.

    Returns a mapping of ``{queue_name: depth}`` for testing convenience.

    This task is scheduled by Celery Beat every minute.  Failure is logged
    but does not propagate — a monitoring task must not disrupt the broker
    or prevent other tasks from running.
    """
    try:
        return _sample_queues()
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "celery.queue_monitor_error",
            extra={
                "event": "celery.queue_monitor_error",
                "error_type": type(exc).__name__,
            },
        )
        return {}


def _sample_queues() -> dict[str, int]:
    """Return a mapping of queue name → pending task count.

    Implementation note: Celery stores tasks in Redis as list keys with the
    same name as the queue.  ``LLEN <queue>`` is an O(1) operation and does
    not affect broker throughput.  The connection uses ``settings.celery_broker_url``
    so it always reads from the same Redis instance as the Celery broker,
    even when ``CELERY_BROKER_URL`` is set to a Redis endpoint that differs
    from ``REDIS_URL``.
    """
    from redis import Redis  # noqa: PLC0415 — imported here to keep module-level import graph lean

    from app.config import settings  # noqa: PLC0415

    depths: dict[str, int] = {}

    with Redis.from_url(settings.celery_broker_url, decode_responses=False, socket_timeout=2) as r:
        for queue in _MONITORED_QUEUES:
            depth = int(r.llen(queue))
            depths[queue] = depth
            logger.info(
                "celery.queue_depth",
                extra={
                    "event": "celery.queue_depth",
                    "queue": queue,
                    "depth": depth,
                },
            )

    return depths
