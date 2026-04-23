"""Embedding service for internal cross-submission similarity detection.

Implements M4.4:
1. Computes and stores a text-embedding vector on an ``EssayVersion`` record.
2. Queries cosine similarity against all other essay versions in the same
   assignment and writes ``IntegrityReport`` records for pairs whose similarity
   exceeds ``settings.integrity_similarity_threshold``
   (env var ``INTEGRITY_SIMILARITY_THRESHOLD``).

Security invariants:
- No essay content is logged at any level.
- Only entity IDs appear in log output.
- ``teacher_id`` is always included in every query to enforce tenant isolation.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.exceptions import ForbiddenError, NotFoundError, ValidationError
from app.models.assignment import Assignment
from app.models.class_ import Class
from app.models.essay import Essay, EssayVersion
from app.models.integrity_report import IntegrityReport, IntegrityReportStatus

logger = logging.getLogger(__name__)


async def compute_and_store_embedding(
    db: AsyncSession,
    essay_version_id: uuid.UUID,
    teacher_id: uuid.UUID,
) -> list[float]:
    """Fetch the essay version, compute its embedding, and persist it.

    The embedding is obtained via :func:`app.llm.client.call_embedding`.
    Tenant isolation is enforced by joining through ``essays → assignments →
    classes`` and filtering on ``teacher_id``.

    Args:
        db: Async database session.
        essay_version_id: UUID of the ``EssayVersion`` to embed.
        teacher_id: The owning teacher's UUID.

    Returns:
        The computed embedding vector as a ``list[float]``.

    Raises:
        NotFoundError: ``EssayVersion`` does not exist.
        ForbiddenError: ``EssayVersion`` exists but belongs to a different
            teacher.
        LLMError: OpenAI call failed after all retries (raised from
            :func:`app.llm.client.call_embedding`).
    """
    from app.llm.client import call_embedding  # noqa: PLC0415 — lazy import

    # Single tenant-scoped query: join + teacher_id filter.
    result = await db.execute(
        select(EssayVersion)
        .join(Essay, EssayVersion.essay_id == Essay.id)
        .join(Assignment, Essay.assignment_id == Assignment.id)
        .join(Class, Assignment.class_id == Class.id)
        .where(EssayVersion.id == essay_version_id, Class.teacher_id == teacher_id)
    )
    version = result.scalars().one_or_none()

    if version is None:
        # Distinguish truly missing from cross-tenant access using a
        # lightweight existence-only query (no data returned).
        exists_result = await db.execute(
            select(EssayVersion.id).where(EssayVersion.id == essay_version_id)
        )
        if exists_result.scalar_one_or_none() is None:
            raise NotFoundError("EssayVersion not found.")
        raise ForbiddenError("You do not have access to this essay version.")

    # Idempotency: if the embedding was already computed (e.g. task was
    # re-enqueued after a partial failure), return it without spending another
    # OpenAI API call.
    if version.embedding is not None:
        logger.info(
            "Essay embedding already exists — skipping recomputation",
            extra={"essay_version_id": str(essay_version_id)},
        )
        return list(version.embedding)

    # Gracefully handle essays with no extractable text (e.g. failed OCR).
    if not (version.content or "").strip():
        raise ValidationError(
            "EssayVersion has no text content — cannot compute embedding."
        )

    # Call the OpenAI embeddings API — may raise LLMError on failure.
    embedding = await call_embedding(version.content)

    version.embedding = embedding
    await db.commit()

    logger.info(
        "Essay embedding computed and stored",
        extra={
            "essay_version_id": str(essay_version_id),
        },
    )
    return embedding


async def flag_similar_essays(
    db: AsyncSession,
    essay_version_id: uuid.UUID,
    assignment_id: uuid.UUID,
    teacher_id: uuid.UUID,
    embedding: list[float],
) -> int:
    """Compare the essay against same-assignment versions and flag similar pairs.

    Queries all other ``EssayVersion`` rows that belong to the same assignment
    and have a stored embedding.  For each pair whose cosine similarity meets
    or exceeds ``settings.integrity_similarity_threshold``, an
    ``IntegrityReport`` record with ``provider="internal"`` is written.

    Cosine similarity is computed as ``1 - cosine_distance`` using
    SQLAlchemy's ``func.cosine_distance(...)`` which maps to pgvector's
    ``cosine_distance()`` SQL function.

    Args:
        db: Async database session.
        essay_version_id: UUID of the source ``EssayVersion`` (the one just
            uploaded and embedded).
        assignment_id: UUID of the parent assignment (used to scope the query).
        teacher_id: The owning teacher's UUID (used for tenant isolation and
            as ``IntegrityReport.teacher_id``).
        embedding: The pre-computed embedding vector for the source essay.

    Returns:
        The number of similarity pairs that were flagged (i.e., the number of
        new ``IntegrityReport`` rows inserted).
    """
    from pgvector.sqlalchemy import Vector  # noqa: PLC0415 — lazy import
    from sqlalchemy import func, literal  # noqa: PLC0415

    # The Settings field_validator already enforces [0, 1] at startup; the
    # assignment here is just for local readability.
    threshold = settings.integrity_similarity_threshold

    embedding_literal = literal(embedding, type_=Vector(1536))

    # Cosine distance via func.cosine_distance():
    #   returns distance in [0, 2]; similarity = 1 - distance.
    #   Flag when similarity >= threshold, i.e. distance <= (1 - threshold).
    #   Push the filter into Postgres so only candidate pairs are transferred
    #   over the network.
    cosine_dist_expr = func.cosine_distance(EssayVersion.embedding, embedding_literal)
    cosine_dist = cosine_dist_expr.label("cosine_dist")

    result = await db.execute(
        select(EssayVersion.id, cosine_dist)
        .join(Essay, EssayVersion.essay_id == Essay.id)
        .join(Assignment, Essay.assignment_id == Assignment.id)
        .join(Class, Assignment.class_id == Class.id)
        .where(
            Essay.assignment_id == assignment_id,
            Class.teacher_id == teacher_id,
            EssayVersion.id != essay_version_id,
            EssayVersion.embedding.is_not(None),
            cosine_dist_expr <= (1.0 - threshold),
        )
    )
    rows = result.all()

    # Fast path: no candidates — skip the dedup DB query entirely.
    if not rows:
        logger.info(
            "Similarity scan complete — no candidates",
            extra={"essay_version_id": str(essay_version_id)},
        )
        return 0

    # Deduplication guard: if a previous run already wrote an internal report
    # for this source version (Celery redelivery or manual re-enqueue), skip
    # all insertions.  Checked once before the loop so that partial runs
    # (e.g. A matched B and C: after B is inserted, C is not skipped) don't
    # happen — the entire similarity scan is idempotent as a unit.
    existing = await db.execute(
        select(IntegrityReport.id)
        .where(
            IntegrityReport.essay_version_id == essay_version_id,
            IntegrityReport.provider == "internal",
        )
        .limit(1)
    )
    if existing.scalar_one_or_none() is not None:
        logger.info(
            "IntegrityReport already exists for this source version — skipping",
            extra={"essay_version_id": str(essay_version_id)},
        )
        return 0

    flagged_count = 0
    for row in rows:
        other_version_id: uuid.UUID = row[0]
        dist: float = float(row[1])
        # Clamp to [0, 1] for two reasons:
        # 1. IntegrityReport.similarity_score is documented as [0.0, 1.0].
        # 2. Floating-point arithmetic can produce tiny values just outside
        #    [0, 1] even for unit vectors (e.g. -1e-9 due to precision).
        similarity = max(0.0, min(1.0, 1.0 - dist))
        rounded_similarity = round(similarity, 4)

        report = IntegrityReport(
            essay_version_id=essay_version_id,
            teacher_id=teacher_id,
            provider="internal",
            similarity_score=rounded_similarity,
            flagged_passages=[
                {
                    "matched_essay_version_id": str(other_version_id),
                    "similarity": rounded_similarity,
                }
            ],
            status=IntegrityReportStatus.pending,
        )
        db.add(report)
        flagged_count += 1

        logger.info(
            "Similarity pair flagged",
            extra={
                "source_essay_version_id": str(essay_version_id),
                "matched_essay_version_id": str(other_version_id),
            },
        )

    if flagged_count:
        await db.commit()

    logger.info(
        "Similarity scan complete",
        extra={
            "essay_version_id": str(essay_version_id),
            "flagged_count": flagged_count,
            "candidates_checked": len(rows),
        },
    )
    return flagged_count
