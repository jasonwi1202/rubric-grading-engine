"""Embedding / integrity Celery task (M4.4 → M4.5).

The :func:`compute_essay_embedding` task runs after a new essay version is
created (triggered by the essay upload router).  It:

1. Fetches the essay text from the database.
2. Calls :func:`app.services.integrity.run_integrity_check`, which selects the
   active :class:`~app.services.integrity.IntegrityProvider` based on the
   ``INTEGRITY_PROVIDER`` environment variable (default: ``"internal"``).
3. The internal provider computes a pgvector embedding and flags similar essays;
   the Originality.ai provider posts to the third-party REST API instead.

Retry behaviour:
- On ``LLMError`` (OpenAI transport failure), the task retries up to 3 times
  with exponential back-off: 2 s, 4 s, 8 s (``2 ** (attempt + 1)``).
- On ``ValidationError`` (empty essay content or misconfigured threshold),
  the task fails immediately without retrying — retrying would not help.
- On ``NotFoundError`` the task fails immediately without retrying — the
  essay/version has been deleted.
- On ``ForbiddenError`` the task fails immediately without retrying — the
  essay/version exists but does not belong to the expected teacher.

Security invariants:
- No essay content is logged at any level.
- Only entity IDs appear in log output.
"""

from __future__ import annotations

import asyncio
import logging
import uuid

from app.db.session import AsyncSessionLocal
from app.exceptions import ForbiddenError, LLMError, NotFoundError, ValidationError
from app.tasks.celery_app import celery

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Async implementation helpers
# ---------------------------------------------------------------------------


async def _run_compute_essay_embedding(
    essay_version_id: str,
    assignment_id: str,
    teacher_id: str,
) -> int:
    """Run the configured integrity provider for the given essay version.

    Calls :func:`app.services.integrity.run_integrity_check` so the active
    provider is determined by the ``INTEGRITY_PROVIDER`` environment variable.

    Returns:
        The number of flagged passages surfaced by the provider.
    """
    from sqlalchemy import select  # noqa: PLC0415

    from app.models.assignment import Assignment  # noqa: PLC0415 — lazy import
    from app.models.class_ import Class  # noqa: PLC0415 — lazy import
    from app.models.essay import Essay, EssayVersion  # noqa: PLC0415 — lazy import
    from app.services.integrity import run_integrity_check  # noqa: PLC0415

    # Tenant-scoped fetch — prevents loading another teacher's essay content
    # into memory before any ownership check runs.
    async with AsyncSessionLocal() as db:
        text_row = await db.execute(
            select(EssayVersion.content)
            .join(Essay, EssayVersion.essay_id == Essay.id)
            .join(Assignment, Essay.assignment_id == Assignment.id)
            .join(Class, Assignment.class_id == Class.id)
            .where(
                EssayVersion.id == uuid.UUID(essay_version_id),
                Essay.assignment_id == uuid.UUID(assignment_id),
                Class.teacher_id == uuid.UUID(teacher_id),
            )
        )
        content = text_row.scalar_one_or_none()
        if content is None:
            # Distinguish 404 (version doesn't exist) from 403 (wrong teacher).
            exists_row = await db.execute(
                select(EssayVersion.id)
                .join(Essay, EssayVersion.essay_id == Essay.id)
                .where(
                    EssayVersion.id == uuid.UUID(essay_version_id),
                    Essay.assignment_id == uuid.UUID(assignment_id),
                )
            )
            if exists_row.scalar_one_or_none() is None:
                raise NotFoundError("EssayVersion not found")
            raise ForbiddenError("You do not have access to this essay version.")
        if not content.strip():
            raise ValidationError("Essay content must not be empty or whitespace-only")
        essay_text: str = content

    async with AsyncSessionLocal() as db:
        result = await run_integrity_check(
            db=db,
            essay_version_id=uuid.UUID(essay_version_id),
            assignment_id=uuid.UUID(assignment_id),
            teacher_id=uuid.UUID(teacher_id),
            essay_text=essay_text,
        )

    return len(result.flagged_passages)


# ---------------------------------------------------------------------------
# Celery task
# ---------------------------------------------------------------------------


@celery.task(  # type: ignore[untyped-decorator]  # Celery stubs are incomplete
    name="tasks.embedding.compute_essay_embedding",
    bind=True,
    max_retries=3,
)
def compute_essay_embedding(
    self: object,
    essay_version_id: str,
    assignment_id: str,
    teacher_id: str,
) -> int:
    """Run the configured integrity provider for the given essay version.

    Determines the active provider via the ``INTEGRITY_PROVIDER`` env var
    (default ``"internal"``).  The internal provider computes a pgvector
    embedding and flags similar essays; external providers (e.g.
    ``originality_ai``) post to a third-party REST API instead.

    Args:
        essay_version_id: UUID string of the ``EssayVersion`` to check.
        assignment_id: UUID string of the parent assignment.  Used to scope
            the integrity check to the same assignment.
        teacher_id: UUID string of the owning teacher.  Used for tenant
            isolation in every database query.

    Returns:
        The number of flagged passages returned by the active provider.

    Raises:
        celery.exceptions.Retry: On ``LLMError`` (OpenAI transport failure),
            with exponential back-off (``2 ** (attempt + 1)`` seconds;
            2 s, 4 s, 8 s).
        Exception: Re-raised after exhausted retries so Celery marks the
            task as ``FAILURE``.
    """
    try:
        return asyncio.run(
            _run_compute_essay_embedding(essay_version_id, assignment_id, teacher_id)
        )
    except (ForbiddenError, NotFoundError):
        # Essay was deleted or never belonged to this teacher — nothing to do.
        logger.warning(
            "Embedding task skipped — essay version not found or forbidden",
            extra={"essay_version_id": essay_version_id},
        )
        raise
    except ValidationError as exc:
        # Empty essay content or misconfigured threshold — retrying won't help.
        logger.warning(
            "Embedding task skipped — validation error (empty content or bad config)",
            extra={
                "essay_version_id": essay_version_id,
                "error_type": type(exc).__name__,
            },
        )
        raise
    except LLMError as exc:
        attempt = self.request.retries  # type: ignore[attr-defined]
        if attempt < self.max_retries:  # type: ignore[attr-defined]
            logger.warning(
                "LLM error in embedding task — will retry",
                extra={
                    "essay_version_id": essay_version_id,
                    "error_type": type(exc).__name__,
                    "attempt": attempt,
                },
            )
            raise self.retry(exc=exc, countdown=2 ** (attempt + 1)) from exc  # type: ignore[attr-defined]

        logger.error(
            "Embedding task failed — retries exhausted",
            extra={
                "essay_version_id": essay_version_id,
                "error_type": type(exc).__name__,
            },
        )
        raise
    except Exception as exc:
        logger.error(
            "Embedding task failed with unrecoverable error",
            extra={
                "essay_version_id": essay_version_id,
                "error_type": type(exc).__name__,
            },
        )
        raise
