"""Celery application instance.

Creates and configures the Celery app using broker and result backend URLs
from application settings.  Import this module to access the ``celery``
singleton::

    from app.tasks.celery_app import celery

The worker is started with::

    celery -A app.tasks.celery_app worker --loglevel=info
"""

from celery import Celery

from app.config import settings

celery = Celery(
    "rubric_grading_engine",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.tasks.debug"],
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
    # Time limits for grading tasks
    task_soft_time_limit=settings.grading_task_soft_time_limit,
    task_time_limit=settings.grading_task_hard_time_limit,
    # Do not store successful task results indefinitely
    result_expires=settings.celery_result_expires_seconds,
)
