"""Media comment service.

Business logic for creating, deleting, and accessing presigned URLs for
audio and video comments attached to grades.

Security invariants:
- All queries include ``teacher_id`` to enforce tenant isolation — no separate
  ownership check followed by an unscoped fetch.
- S3 keys follow the format ``media/{teacher_id}/{grade_id}/{uuid}.webm``
  so no student PII ever appears in a key.
- S3 object keys are never logged or included in exception messages.
- No student PII in any log statement — only entity IDs are logged.
"""

from __future__ import annotations

import asyncio
import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import ForbiddenError, NotFoundError, ValidationError
from app.models.assignment import Assignment
from app.models.class_ import Class
from app.models.essay import Essay, EssayVersion
from app.models.grade import Grade
from app.models.media_comment import MediaComment
from app.schemas.media_comment import (
    MediaCommentResponse,
    MediaCommentUrlResponse,
    SaveToBankResponse,
)
from app.storage.s3 import StorageError, copy_file, delete_file, generate_presigned_url, upload_file

logger = logging.getLogger(__name__)

# Maximum media recording size: 50 MB.
MAX_MEDIA_SIZE_BYTES = 50 * 1024 * 1024

# Allowed MIME types for audio and video comments.
ALLOWED_MIME_TYPES = frozenset(
    [
        "audio/webm",
        "audio/webm;codecs=opus",
        "audio/ogg",
        "audio/ogg;codecs=opus",
        "audio/mp4",
        "video/webm",
        "video/webm;codecs=vp8,opus",
        "video/webm;codecs=vp9,opus",
    ]
)

# Mapping from base MIME type to S3 object key extension.
# Keys must be a subset of the base MIME types derived from ALLOWED_MIME_TYPES;
# the router validates the MIME type before calling any service function, so
# a type outside this mapping should never reach create_media_comment.
# Used to ensure the stored file has the correct extension even when the
# client sends a non-webm recording (e.g. Safari sends audio/mp4).
_MIME_TO_EXT: dict[str, str] = {
    "audio/webm": ".webm",
    "audio/ogg": ".ogg",
    "audio/mp4": ".mp4",
    "video/webm": ".webm",
}

# Sanity-check: every base MIME type in ALLOWED_MIME_TYPES must have an entry
# in _MIME_TO_EXT, so adding a new allowed type without a corresponding
# extension mapping is caught immediately at import time.
assert all(
    m.split(";")[0].strip() in _MIME_TO_EXT for m in ALLOWED_MIME_TYPES
), "All base MIME types in ALLOWED_MIME_TYPES must have an entry in _MIME_TO_EXT"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _load_grade_tenant_scoped(
    db: AsyncSession,
    grade_id: uuid.UUID,
    teacher_id: uuid.UUID,
) -> Grade:
    """Load a Grade, enforcing tenant isolation via the full ownership chain.

    ``teacher_id`` is included in the query itself — not as a separate ownership
    check — to satisfy the repo's tenant-isolation invariant that every data
    query must include ``teacher_id`` directly.

    Raises NotFoundError if the grade does not exist.
    Raises ForbiddenError if it belongs to a different teacher.
    """
    stmt = (
        select(Grade)
        .join(EssayVersion, Grade.essay_version_id == EssayVersion.id)
        .join(Essay, EssayVersion.essay_id == Essay.id)
        .join(Assignment, Essay.assignment_id == Assignment.id)
        .join(Class, Assignment.class_id == Class.id)
        .where(Grade.id == grade_id, Class.teacher_id == teacher_id)
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
    """Upload audio or video to S3 and persist a MediaComment record.

    Args:
        db: Async database session.
        grade_id: UUID of the grade to attach the comment to.
        teacher_id: UUID of the authenticated teacher.
        audio_bytes: Raw media blob bytes (audio or video).
        duration_seconds: Recording length in seconds (client-supplied).
        mime_type: MIME type of the recording (e.g. ``"audio/webm"`` or ``"video/webm"``).

    Returns:
        The created :class:`MediaCommentResponse`.

    Raises:
        NotFoundError: Grade not found.
        ForbiddenError: Grade belongs to a different teacher.
    """
    # Validate ownership before touching S3.
    await _load_grade_tenant_scoped(db, grade_id, teacher_id)

    comment_id = uuid.uuid4()
    base_mime = mime_type.split(";")[0].strip()
    # The router validates the MIME type against ALLOWED_MIME_TYPES before
    # calling this function, so base_mime is guaranteed to be in _MIME_TO_EXT.
    # A KeyError here indicates a programming error (e.g. a new MIME type was
    # added to ALLOWED_MIME_TYPES without a matching entry in _MIME_TO_EXT).
    ext = _MIME_TO_EXT[base_mime]
    s3_key = f"media/{teacher_id}/{grade_id}/{comment_id}{ext}"
    loop = asyncio.get_running_loop()

    # Upload to S3 in a thread pool so the sync boto3 call does not block the
    # event loop.  Any StorageError propagates to the caller (mapped to 500).
    await loop.run_in_executor(None, upload_file, s3_key, audio_bytes, mime_type)

    mc = MediaComment(
        id=comment_id,
        grade_id=grade_id,
        teacher_id=teacher_id,
        s3_key=s3_key,
        duration_seconds=duration_seconds,
        mime_type=mime_type,
    )
    try:
        db.add(mc)
        await db.flush()
        await db.refresh(mc)
        await db.commit()
    except Exception as exc:
        await db.rollback()
        # Best-effort cleanup: remove the S3 object that was already uploaded.
        try:
            await loop.run_in_executor(None, delete_file, s3_key)
        except Exception as cleanup_exc:
            logger.error(
                "media_comment_s3_cleanup_failed",
                extra={
                    "grade_id": str(grade_id),
                    "media_comment_id": str(comment_id),
                    "error_type": type(cleanup_exc).__name__,
                },
            )
        logger.error(
            "media_comment_create_db_write_failed",
            extra={
                "grade_id": str(grade_id),
                "media_comment_id": str(comment_id),
                "error_type": type(exc).__name__,
            },
        )
        raise

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
        is_banked=mc.is_banked,
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

    # Best-effort S3 deletion: the DB row is already gone, so a storage failure
    # is a storage-cost concern only, not a data-integrity one.  Log and
    # continue rather than surfacing a 500 after a successful DB delete.
    loop = asyncio.get_running_loop()
    try:
        await loop.run_in_executor(None, delete_file, s3_key)
    except StorageError as exc:
        logger.error(
            "media_comment_s3_delete_failed",
            extra={
                "media_comment_id": str(media_comment_id),
                "error_type": type(exc).__name__,
            },
        )

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

    loop = asyncio.get_running_loop()
    url = await loop.run_in_executor(None, generate_presigned_url, mc.s3_key)

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
            is_banked=r.is_banked,
            created_at=r.created_at,
        )
        for r in rows
    ]


async def save_to_bank(
    db: AsyncSession,
    media_comment_id: uuid.UUID,
    teacher_id: uuid.UUID,
) -> SaveToBankResponse:
    """Mark a media comment as saved to the teacher's reusable bank.

    Args:
        db: Async database session.
        media_comment_id: UUID of the MediaComment to bank.
        teacher_id: UUID of the authenticated teacher.

    Returns:
        :class:`SaveToBankResponse` with updated ``is_banked`` flag.

    Raises:
        NotFoundError: Media comment not found.
        ForbiddenError: Media comment belongs to a different teacher.
    """
    mc = await _load_media_comment_tenant_scoped(db, media_comment_id, teacher_id)

    mc.is_banked = True
    await db.commit()
    await db.refresh(mc)

    logger.info(
        "media_comment_saved_to_bank",
        extra={"media_comment_id": str(media_comment_id)},
    )
    return SaveToBankResponse(id=mc.id, is_banked=mc.is_banked)


async def list_banked_media_comments(
    db: AsyncSession,
    teacher_id: uuid.UUID,
) -> list[MediaCommentResponse]:
    """Return all banked media comments for a teacher, newest first.

    Args:
        db: Async database session.
        teacher_id: UUID of the authenticated teacher.

    Returns:
        List of :class:`MediaCommentResponse` objects where ``is_banked`` is True.
    """
    stmt = (
        select(MediaComment)
        .where(
            MediaComment.teacher_id == teacher_id,
            MediaComment.is_banked == True,  # noqa: E712 — SQLAlchemy requires ==
        )
        .order_by(MediaComment.created_at.desc())
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
            is_banked=r.is_banked,
            created_at=r.created_at,
        )
        for r in rows
    ]


async def apply_banked_comment(
    db: AsyncSession,
    grade_id: uuid.UUID,
    teacher_id: uuid.UUID,
    source_id: uuid.UUID,
) -> MediaCommentResponse:
    """Apply a banked media comment to a new grade by copying the S3 object.

    The source comment's S3 object is copied to a new key scoped to the target
    grade.  A new :class:`MediaComment` record is created for the target grade.
    The source comment remains unchanged.

    Args:
        db: Async database session.
        grade_id: UUID of the target grade.
        teacher_id: UUID of the authenticated teacher.
        source_id: UUID of the banked :class:`MediaComment` to copy.

    Returns:
        The newly created :class:`MediaCommentResponse`.

    Raises:
        NotFoundError: Source media comment or target grade not found.
        ForbiddenError: Source comment or target grade belongs to a different teacher.
        ValidationError: Source comment is not banked.
    """
    # Validate target grade ownership.
    await _load_grade_tenant_scoped(db, grade_id, teacher_id)

    # Load the source comment — must be owned by the same teacher.
    source = await _load_media_comment_tenant_scoped(db, source_id, teacher_id)

    # Only banked comments may be applied; applying an unbanked comment is a
    # caller error, not a permissions issue.
    if not source.is_banked:
        raise ValidationError(
            "Media comment has not been saved to the bank and cannot be applied.",
            field="source_id",
        )

    # Derive file extension from the source MIME type.
    base_mime = source.mime_type.split(";")[0].strip()
    ext = _MIME_TO_EXT.get(base_mime, ".webm")
    new_comment_id = uuid.uuid4()
    dest_key = f"media/{teacher_id}/{grade_id}/{new_comment_id}{ext}"

    loop = asyncio.get_running_loop()
    # Copy the S3 object so each grade has its own independent media file.
    # A StorageError here propagates to the caller (mapped to 500).
    await loop.run_in_executor(None, copy_file, source.s3_key, dest_key)

    mc = MediaComment(
        id=new_comment_id,
        grade_id=grade_id,
        teacher_id=teacher_id,
        s3_key=dest_key,
        duration_seconds=source.duration_seconds,
        mime_type=source.mime_type,
        is_banked=False,
    )
    try:
        db.add(mc)
        await db.flush()
        await db.refresh(mc)
        await db.commit()
    except Exception as exc:
        await db.rollback()
        # Best-effort cleanup of the copied S3 object.
        try:
            await loop.run_in_executor(None, delete_file, dest_key)
        except Exception as cleanup_exc:
            logger.error(
                "media_comment_s3_cleanup_failed",
                extra={
                    "grade_id": str(grade_id),
                    "media_comment_id": str(new_comment_id),
                    "error_type": type(cleanup_exc).__name__,
                },
            )
        logger.error(
            "media_comment_apply_bank_db_write_failed",
            extra={
                "grade_id": str(grade_id),
                "source_id": str(source_id),
                "error_type": type(exc).__name__,
            },
        )
        raise

    logger.info(
        "media_comment_applied_from_bank",
        extra={
            "grade_id": str(grade_id),
            "source_id": str(source_id),
            "media_comment_id": str(mc.id),
        },
    )
    return MediaCommentResponse(
        id=mc.id,
        grade_id=mc.grade_id,
        s3_key=mc.s3_key,
        duration_seconds=mc.duration_seconds,
        mime_type=mc.mime_type,
        is_banked=mc.is_banked,
        created_at=mc.created_at,
    )
