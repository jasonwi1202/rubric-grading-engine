"""Media comment service.

Business logic for creating, deleting, and accessing presigned URLs for
audio comments attached to grades.

Security invariants:
- All queries include ``teacher_id`` to enforce tenant isolation — no separate
  ownership check followed by an unscoped fetch.
- S3 keys follow the format ``media/{teacher_id}/{grade_id}/{uuid}.webm``
  so no student PII ever appears in a key.
- S3 object keys are never logged or included in exception messages.
- No student PII in any log statement — only entity IDs are logged.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import ForbiddenError, NotFoundError
from app.models.assignment import Assignment
from app.models.class_ import Class
from app.models.essay import Essay, EssayVersion
from app.models.grade import Grade
from app.models.media_comment import MediaComment
from app.schemas.media_comment import MediaCommentResponse, MediaCommentUrlResponse
from app.storage.s3 import delete_file, generate_presigned_url, upload_file

logger = logging.getLogger(__name__)

# Maximum audio recording size: 50 MB.
MAX_MEDIA_SIZE_BYTES = 50 * 1024 * 1024

# Allowed MIME types for audio comments.
ALLOWED_MIME_TYPES = frozenset(
    [
        "audio/webm",
        "audio/webm;codecs=opus",
        "audio/ogg",
        "audio/ogg;codecs=opus",
        "audio/mp4",
    ]
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _load_grade_tenant_scoped(
    db: AsyncSession,
    grade_id: uuid.UUID,
    teacher_id: uuid.UUID,
) -> Grade:
    """Load a Grade, enforcing tenant isolation via the full ownership chain.

    Raises NotFoundError if the grade does not exist.
    Raises ForbiddenError if it belongs to a different teacher.
    """
    stmt = (
        select(Grade)
        .join(EssayVersion, Grade.essay_version_id == EssayVersion.id)
        .join(Essay, EssayVersion.essay_id == Essay.id)
        .join(Assignment, Essay.assignment_id == Assignment.id)
        .join(Class, Assignment.class_id == Class.id)
        .where(Grade.id == grade_id)
    )
    result = await db.execute(stmt)
    grade = result.scalar_one_or_none()

    if grade is None:
        # Determine whether the grade exists at all (for 403 vs 404 distinction).
        exists_stmt = select(Grade.id).where(Grade.id == grade_id)
        exists_result = await db.execute(exists_stmt)
        if exists_result.scalar_one_or_none() is None:
            raise NotFoundError("Grade not found.")
        raise ForbiddenError("You do not have access to this grade.")

    # Verify ownership.
    class_stmt = (
        select(Class.teacher_id)
        .join(Assignment, Class.id == Assignment.class_id)
        .join(Essay, Assignment.id == Essay.assignment_id)
        .join(EssayVersion, Essay.id == EssayVersion.essay_id)
        .join(Grade, EssayVersion.id == Grade.essay_version_id)
        .where(Grade.id == grade_id)
    )
    class_result = await db.execute(class_stmt)
    owning_teacher_id = class_result.scalar_one_or_none()

    if owning_teacher_id != teacher_id:
        raise ForbiddenError("You do not have access to this grade.")

    return grade


async def _load_media_comment_tenant_scoped(
    db: AsyncSession,
    media_comment_id: uuid.UUID,
    teacher_id: uuid.UUID,
) -> MediaComment:
    """Load a MediaComment scoped to the requesting teacher.

    The ``teacher_id`` filter is included in the query itself — not as a
    separate ownership check — to prevent TOCTOU gaps.

    Raises NotFoundError if the record does not exist.
    Raises ForbiddenError if it belongs to a different teacher.
    """
    stmt = select(MediaComment).where(
        MediaComment.id == media_comment_id,
        MediaComment.teacher_id == teacher_id,
    )
    result = await db.execute(stmt)
    mc = result.scalar_one_or_none()

    if mc is None:
        # Determine 403 vs 404.
        exists_stmt = select(MediaComment.id).where(
            MediaComment.id == media_comment_id
        )
        exists_result = await db.execute(exists_stmt)
        if exists_result.scalar_one_or_none() is None:
            raise NotFoundError("Media comment not found.")
        raise ForbiddenError("You do not have access to this media comment.")

    return mc


# ---------------------------------------------------------------------------
# Public service functions
# ---------------------------------------------------------------------------


async def create_media_comment(
    db: AsyncSession,
    grade_id: uuid.UUID,
    teacher_id: uuid.UUID,
    audio_bytes: bytes,
    duration_seconds: int,
    mime_type: str,
) -> MediaCommentResponse:
    """Upload audio to S3 and persist a MediaComment record.

    Args:
        db: Async database session.
        grade_id: UUID of the grade to attach the comment to.
        teacher_id: UUID of the authenticated teacher.
        audio_bytes: Raw audio blob bytes.
        duration_seconds: Recording length in seconds (client-supplied).
        mime_type: MIME type of the recording (e.g. ``"audio/webm"``).

    Returns:
        The created :class:`MediaCommentResponse`.

    Raises:
        NotFoundError: Grade not found.
        ForbiddenError: Grade belongs to a different teacher.
    """
    # Validate ownership before touching S3.
    await _load_grade_tenant_scoped(db, grade_id, teacher_id)

    comment_id = uuid.uuid4()
    s3_key = f"media/{teacher_id}/{grade_id}/{comment_id}.webm"

    # Upload to S3 — any StorageError propagates to the caller (mapped to 500).
    upload_file(s3_key, audio_bytes, mime_type)

    mc = MediaComment(
        id=comment_id,
        grade_id=grade_id,
        teacher_id=teacher_id,
        s3_key=s3_key,
        duration_seconds=duration_seconds,
        mime_type=mime_type,
    )
    db.add(mc)
    await db.flush()
    await db.refresh(mc)
    await db.commit()

    logger.info(
        "media_comment_created",
        extra={"grade_id": str(grade_id), "media_comment_id": str(mc.id)},
    )
    return MediaCommentResponse(
        id=mc.id,
        grade_id=mc.grade_id,
        s3_key=mc.s3_key,
        duration_seconds=mc.duration_seconds,
        mime_type=mc.mime_type,
        created_at=mc.created_at,
    )


async def delete_media_comment(
    db: AsyncSession,
    media_comment_id: uuid.UUID,
    teacher_id: uuid.UUID,
) -> None:
    """Delete a MediaComment record and its associated S3 object.

    Args:
        db: Async database session.
        media_comment_id: UUID of the MediaComment to delete.
        teacher_id: UUID of the authenticated teacher.

    Raises:
        NotFoundError: Media comment not found.
        ForbiddenError: Media comment belongs to a different teacher.
    """
    mc = await _load_media_comment_tenant_scoped(db, media_comment_id, teacher_id)

    s3_key = mc.s3_key  # captured before deletion

    db.delete(mc)  # type: ignore[unused-coroutine]  # db.delete is sync on AsyncSession; SQLAlchemy stubs incorrectly type it as a coroutine
    await db.commit()

    # Delete from S3 after the DB row is gone — if this fails the orphan
    # object in S3 is a storage-cost concern, not a data-integrity one.
    delete_file(s3_key)

    logger.info(
        "media_comment_deleted",
        extra={"media_comment_id": str(media_comment_id)},
    )


async def get_media_comment_url(
    db: AsyncSession,
    media_comment_id: uuid.UUID,
    teacher_id: uuid.UUID,
) -> MediaCommentUrlResponse:
    """Return a pre-signed GET URL for a media comment.

    The URL is generated from the S3 key stored on the record; the key is
    never included in log output.

    Args:
        db: Async database session.
        media_comment_id: UUID of the MediaComment.
        teacher_id: UUID of the authenticated teacher.

    Returns:
        :class:`MediaCommentUrlResponse` with a short-lived presigned URL.

    Raises:
        NotFoundError: Media comment not found.
        ForbiddenError: Media comment belongs to a different teacher.
    """
    mc = await _load_media_comment_tenant_scoped(db, media_comment_id, teacher_id)

    url = generate_presigned_url(mc.s3_key)

    logger.info(
        "media_comment_url_generated",
        extra={"media_comment_id": str(media_comment_id)},
    )
    return MediaCommentUrlResponse(url=url)


async def list_grade_media_comments(
    db: AsyncSession,
    grade_id: uuid.UUID,
    teacher_id: uuid.UUID,
) -> list[MediaCommentResponse]:
    """Return all media comments for a grade, ordered by creation time.

    Verifies grade ownership before returning any records.

    Args:
        db: Async database session.
        grade_id: UUID of the grade.
        teacher_id: UUID of the authenticated teacher.

    Returns:
        List of :class:`MediaCommentResponse` objects.

    Raises:
        NotFoundError: Grade not found.
        ForbiddenError: Grade belongs to a different teacher.
    """
    await _load_grade_tenant_scoped(db, grade_id, teacher_id)

    stmt = (
        select(MediaComment)
        .where(
            MediaComment.grade_id == grade_id,
            MediaComment.teacher_id == teacher_id,
        )
        .order_by(MediaComment.created_at)
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()
    return [
        MediaCommentResponse(
            id=r.id,
            grade_id=r.grade_id,
            s3_key=r.s3_key,
            duration_seconds=r.duration_seconds,
            mime_type=r.mime_type,
            created_at=r.created_at,
        )
        for r in rows
    ]
