"""Debug / smoke-test Celery tasks.

These tasks exist solely to verify that the Celery worker and Redis broker
are wired up correctly.  They must not be used for any production workload.

Usage::

    from app.tasks.debug import ping

    result = ping.delay("hello")
    assert result.get(timeout=5) == "hello"
"""

from app.tasks.celery_app import celery


@celery.task(name="tasks.debug.ping")  # type: ignore[untyped-decorator]  # celery stubs are incomplete
def ping(message: str) -> str:
    """Accept a string and return it unchanged.

    This is a smoke-test task used to confirm that the Celery worker is
    running and can process tasks via the Redis broker.
    """
    return message
