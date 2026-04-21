"""Comment bank service.

Business logic for comment bank CRUD operations and fuzzy-match suggestions:

- ``list_comments``     — list all saved comments for a teacher.
- ``create_comment``    — save a new feedback snippet.
- ``delete_comment``    — remove a saved comment (tenant-scoped).
- ``suggest_comments``  — return saved comments whose text fuzzy-matches a query.

Fuzzy matching uses ``rapidfuzz.fuzz.partial_ratio`` (0–100 scale, converted
to a 0.0–1.0 score).  Only entries scoring above ``_SUGGESTION_THRESHOLD``
are returned, ordered by descending score.

No student PII is collected or processed here.
"""

from __future__ import annotations

import logging
import uuid

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
    """Return all saved comments for a teacher, newest first."""
    result = await db.execute(
        select(CommentBankEntry)
        .where(CommentBankEntry.teacher_id == teacher_id)
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
    """Delete a saved comment.

    Raises:
        NotFoundError: If the comment does not exist.
        ForbiddenError: If the comment belongs to a different teacher.
    """
    result = await db.execute(select(CommentBankEntry).where(CommentBankEntry.id == comment_id))
    entry = result.scalar_one_or_none()

    if entry is None:
        raise NotFoundError("Comment not found.")
    if entry.teacher_id != teacher_id:
        raise ForbiddenError("You do not have access to this comment.")

    db.delete(entry)  # type: ignore[unused-coroutine]  # db.delete is sync on AsyncSession; SQLAlchemy stubs incorrectly type it as a coroutine
    await db.commit()

    logger.info(
        "Comment bank entry deleted",
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
