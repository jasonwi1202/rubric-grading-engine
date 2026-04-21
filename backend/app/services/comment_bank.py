"""Comment bank service.

Business logic for comment bank CRUD operations and fuzzy-match suggestions:

- ``list_comments``     — list all saved comments for a teacher.
- ``create_comment``    — save a new feedback snippet.
- ``delete_comment``    — soft-delete a saved comment (tenant-scoped).
- ``suggest_comments``  — return saved comments whose text fuzzy-matches a query.

Fuzzy matching uses ``rapidfuzz.fuzz.partial_ratio`` (0–100 scale, converted
to a 0.0–1.0 score).  Only entries scoring above ``_SUGGESTION_THRESHOLD``
are returned, ordered by descending score.

Do not log comment text; treat it as potentially containing student PII.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from rapidfuzz import fuzz
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import ForbiddenError, NotFoundError
from app.models.comment_bank import CommentBankEntry

logger = logging.getLogger(__name__)

# Minimum fuzzy-match score (0–100 scale) for a comment to be suggested.
_SUGGESTION_THRESHOLD = 50


# ---------------------------------------------------------------------------
# Public service functions
# ---------------------------------------------------------------------------


async def list_comments(
    db: AsyncSession,
    teacher_id: uuid.UUID,
) -> list[CommentBankEntry]:
    """Return all active (non-deleted) saved comments for a teacher, newest first."""
    result = await db.execute(
        select(CommentBankEntry)
        .where(
            CommentBankEntry.teacher_id == teacher_id,
            CommentBankEntry.deleted_at.is_(None),
        )
        .order_by(CommentBankEntry.created_at.desc())
    )
    return list(result.scalars().all())


async def create_comment(
    db: AsyncSession,
    teacher_id: uuid.UUID,
    text: str,
) -> CommentBankEntry:
    """Save a new feedback comment snippet for a teacher.

    Returns the newly created :class:`CommentBankEntry`.
    """
    entry = CommentBankEntry(teacher_id=teacher_id, text=text)
    db.add(entry)
    await db.commit()
    await db.refresh(entry)

    logger.info(
        "Comment bank entry created",
        extra={"comment_id": str(entry.id), "teacher_id": str(teacher_id)},
    )
    return entry


async def delete_comment(
    db: AsyncSession,
    teacher_id: uuid.UUID,
    comment_id: uuid.UUID,
) -> None:
    """Soft-delete a saved comment by setting ``deleted_at`` to now.

    Raises:
        NotFoundError: If the comment does not exist or is already deleted.
        ForbiddenError: If the comment belongs to a different teacher.
    """
    ownership_result = await db.execute(
        select(CommentBankEntry.id, CommentBankEntry.teacher_id).where(
            CommentBankEntry.id == comment_id,
            CommentBankEntry.deleted_at.is_(None),
        )
    )
    ownership = ownership_result.one_or_none()

    if ownership is None:
        raise NotFoundError("Comment not found.")
    if ownership.teacher_id != teacher_id:
        raise ForbiddenError("You do not have access to this comment.")

    entry_result = await db.execute(
        select(CommentBankEntry).where(
            CommentBankEntry.id == comment_id,
            CommentBankEntry.teacher_id == teacher_id,
            CommentBankEntry.deleted_at.is_(None),
        )
    )
    entry = entry_result.scalar_one_or_none()
    if entry is None:
        raise NotFoundError("Comment not found.")

    entry.deleted_at = datetime.now(UTC)
    await db.commit()

    logger.info(
        "Comment bank entry soft-deleted",
        extra={"comment_id": str(comment_id), "teacher_id": str(teacher_id)},
    )


async def suggest_comments(
    db: AsyncSession,
    teacher_id: uuid.UUID,
    query: str,
) -> list[tuple[CommentBankEntry, float]]:
    """Return saved comments whose text fuzzy-matches *query*.

    Uses ``rapidfuzz.fuzz.partial_ratio`` so that short query strings still
    match longer stored comments when they appear as a substring.  Returns
    only entries whose score exceeds ``_SUGGESTION_THRESHOLD``, sorted by
    descending score.

    The returned score is normalised to the range 0.0–1.0.
    """
    entries = await list_comments(db, teacher_id)

    scored: list[tuple[CommentBankEntry, float]] = []
    for entry in entries:
        raw_score: float = fuzz.partial_ratio(query.lower(), entry.text.lower())
        if raw_score >= _SUGGESTION_THRESHOLD:
            scored.append((entry, raw_score / 100.0))

    scored.sort(key=lambda t: t[1], reverse=True)
    return scored
