"""Embedding service for internal cross-submission similarity detection.

Implements M4.4:
1. Computes and stores a text-embedding vector on an ``EssayVersion`` record.
2. Queries cosine similarity against all other essay versions in the same
   assignment and writes ``IntegrityReport`` records for pairs whose similarity
   exceeds ``settings.integrity_similarity_threshold``.

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
from app.exceptions import ForbiddenError, NotFoundError
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
        ForbiddenError: ``EssayVersion`` belongs to a different teacher.
        LLMError: OpenAI call failed after all retries (raised from
            :func:`app.llm.client.call_embedding`).
    """
    from app.llm.client import call_embedding  # noqa: PLC0415 — lazy import

    # Ownership-aware load: JOIN ensures teacher_id scoping in a single query.
    result = await db.execute(
        select(EssayVersion, Class.teacher_id.label("class_teacher_id"))
        .join(Essay, EssayVersion.essay_id == Essay.id)
        .join(Assignment, Essay.assignment_id == Assignment.id)
        .join(Class, Assignment.class_id == Class.id)
        .where(EssayVersion.id == essay_version_id)
    )
    row = result.one_or_none()

    if row is None:
        raise NotFoundError("EssayVersion not found.")

    version, class_teacher_id = row
    if class_teacher_id != teacher_id:
        raise ForbiddenError("EssayVersion does not belong to this teacher.")

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

    Cosine similarity is computed as ``1 - cosine_distance`` where the
    ``<=>`` pgvector operator provides the cosine distance.

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

    threshold = settings.integrity_similarity_threshold

    # Cosine distance via pgvector's <=> operator:
    #   func.cosine_distance(a, b) returns distance in [0, 2]; we want
    #   similarity = 1 − distance.  Flag when similarity >= threshold,
    #   i.e. distance <= (1 − threshold).
    cosine_dist = func.cosine_distance(
        EssayVersion.embedding,
        literal(embedding, type_=Vector(1536)),
    ).label("cosine_dist")

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
        )
    )
    rows = result.all()

    flagged_count = 0
    for row in rows:
        other_version_id: uuid.UUID = row[0]
        dist: float = float(row[1])
        similarity = 1.0 - dist

        if similarity < threshold:
            continue

        report = IntegrityReport(
            essay_version_id=essay_version_id,
            teacher_id=teacher_id,
            provider="internal",
            similarity_score=round(similarity, 4),
            flagged_passages=[
                {
                    "matched_essay_version_id": str(other_version_id),
                    "similarity": round(similarity, 4),
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
