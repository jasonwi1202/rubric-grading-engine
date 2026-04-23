"""Embedding Celery task for internal cross-submission similarity (M4.4).

The :func:`compute_essay_embedding` task runs after a new essay version is
created (triggered by the essay upload router).  It:

1. Calls the OpenAI Embeddings API to produce a 1536-dimension vector for
   the essay text.
2. Stores the vector in the ``essay_versions.embedding`` column.
3. Queries cosine similarity against all other embedded essay versions in the
   same assignment and writes ``IntegrityReport`` records (``provider="internal"``)
   for any pair whose similarity meets or exceeds ``INTEGRITY_SIMILARITY_THRESHOLD``.

Retry behaviour:
- On ``LLMError`` (OpenAI transport failure), the task retries up to 3 times
  with exponential back-off (2, 4, 8 seconds).
- On ``ForbiddenError`` or ``NotFoundError`` the task fails immediately
  without retrying — the essay/version no longer belongs to the expected
  teacher or has been deleted.

Security invariants:
- No essay content is logged at any level.
- Only entity IDs appear in log output.
"""

from __future__ import annotations

import asyncio
import logging
import uuid

from app.db.session import AsyncSessionLocal
from app.exceptions import ForbiddenError, LLMError, NotFoundError
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
    """Compute and store an embedding, then flag similar pairs.

    Returns the number of similarity pairs flagged.
    """
    from app.services.embedding import (  # noqa: PLC0415
        compute_and_store_embedding,
        flag_similar_essays,
    )

    async with AsyncSessionLocal() as db:
        embedding = await compute_and_store_embedding(
            db=db,
            essay_version_id=uuid.UUID(essay_version_id),
            teacher_id=uuid.UUID(teacher_id),
        )

    # Run the similarity scan in a fresh session so the embedding commit above
    # is visible to the similarity query.
    async with AsyncSessionLocal() as db:
        flagged = await flag_similar_essays(
            db=db,
            essay_version_id=uuid.UUID(essay_version_id),
            assignment_id=uuid.UUID(assignment_id),
            teacher_id=uuid.UUID(teacher_id),
            embedding=embedding,
        )

    return flagged


# ---------------------------------------------------------------------------
# Celery task
# ---------------------------------------------------------------------------


@celery.task(  # type: ignore[untyped-decorator]
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
    """Compute an essay embedding and flag similar submissions.

    Args:
        essay_version_id: UUID string of the ``EssayVersion`` to embed.
        assignment_id: UUID string of the parent assignment.  Used to scope
            the cosine-similarity search to the same assignment.
        teacher_id: UUID string of the owning teacher.  Used for tenant
            isolation in every database query.

    Returns:
        The number of similarity pairs written to ``integrity_reports``.

    Raises:
        celery.exceptions.Retry: On ``LLMError`` (OpenAI transport failure),
            with exponential back-off (``2 ** attempt`` seconds).
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
            raise self.retry(exc=exc, countdown=2**attempt) from exc  # type: ignore[attr-defined]

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
