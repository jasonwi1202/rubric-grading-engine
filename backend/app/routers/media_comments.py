"""Media comment router.

Endpoints:
  POST   /grades/{grade_id}/media-comments          — upload audio or video, create record
                                                      OR apply banked comment via source_id
  GET    /grades/{grade_id}/media-comments          — list all comments for a grade
  DELETE /media-comments/{media_comment_id}         — delete record and S3 object
  GET    /media-comments/{media_comment_id}/url     — get presigned playback URL
  POST   /media-comments/{media_comment_id}/save-to-bank — mark comment as banked
  GET    /media-comments/bank                       — list all banked comments for a teacher

All endpoints require a valid JWT (``get_current_teacher`` dependency).
No student PII is logged — only entity IDs appear in log output.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import JSONResponse, Response

from app.db.session import AsyncSession, get_db
from app.dependencies import get_current_teacher
from app.exceptions import ValidationError
from app.models.user import User
from app.services.media_comment import (
    ALLOWED_MIME_TYPES,
    MAX_MEDIA_SIZE_BYTES,
    apply_banked_comment,
    create_media_comment,
    delete_media_comment,
    get_media_comment_url,
    list_banked_media_comments,
    list_grade_media_comments,
    save_to_bank,
)

#: Pre-computed set of base MIME types (without codec parameters) for efficient
#: per-request validation without rebuilding the set on every call.
_ALLOWED_BASE_MIME_TYPES: frozenset[str] = frozenset(
    m.split(";")[0].strip() for m in ALLOWED_MIME_TYPES
)

#: Router for grade-scoped media comment operations.
grade_media_router = APIRouter(prefix="/grades", tags=["media-comments"])

#: Router for individual media comment operations.
media_comments_router = APIRouter(prefix="/media-comments", tags=["media-comments"])


# ---------------------------------------------------------------------------
# POST /grades/{grade_id}/media-comments
# ---------------------------------------------------------------------------


@grade_media_router.post(
    "/{grade_id}/media-comments",
    status_code=201,
    summary="Upload an audio or video comment and associate it with a grade",
)
async def create_media_comment_endpoint(
    grade_id: uuid.UUID,
    file: UploadFile | None = File(
        None, description="Media blob (audio/webm, audio/ogg, audio/mp4, video/webm)"
    ),
    duration_seconds: int | None = Form(None, ge=1, le=180),
    source_id: uuid.UUID | None = Form(
        None, description="UUID of a banked media comment to apply instead of uploading a new file"
    ),
    teacher: User = Depends(get_current_teacher),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Upload an audio or video recording and create a MediaComment record.

    Two modes:
    - **Upload mode** (default): send ``file`` + ``duration_seconds`` as multipart/form-data.
      The media blob is uploaded to S3 under the key
      ``media/{teacher_id}/{grade_id}/{uuid}.webm``.
    - **Apply-from-bank mode**: send ``source_id`` pointing to a banked media comment.
      The source S3 object is copied to a new key for the target grade.

    Response body: ``{"data": MediaCommentResponse}``

    Returns 422 if the file is too large or the MIME type is not allowed.
    Returns 403 if the grade belongs to a different teacher.
    Returns 404 if the grade does not exist.
    """
    # --- Apply-from-bank mode ---
    if source_id is not None:
        # Mutual exclusivity: reject if the caller also sends a file upload.
        if file is not None:
            raise ValidationError(
                "'source_id' and 'file' are mutually exclusive. "
                "Provide 'source_id' to apply a banked comment, or 'file' + "
                "'duration_seconds' to upload a new recording.",
                field="source_id",
            )
        response = await apply_banked_comment(
            db=db,
            grade_id=grade_id,
            teacher_id=teacher.id,
            source_id=source_id,
        )
        return JSONResponse(
            status_code=201,
            content={"data": response.model_dump(mode="json")},
        )

    # --- Upload mode ---
    if file is None or duration_seconds is None:
        raise ValidationError(
            "Either 'source_id' or both 'file' and 'duration_seconds' must be provided.",
            field="file",
        )

    # Normalise mime type (strip trailing whitespace / params for comparison).
    mime_type = (file.content_type or "").strip()
    base_mime = mime_type.split(";")[0].strip()
    if base_mime not in _ALLOWED_BASE_MIME_TYPES:
        raise ValidationError(
            f"MIME type {base_mime!r} is not allowed for media comments.",
            field="file",
        )

    # Read in chunks so we can reject oversized files without buffering the
    # entire upload into memory first.
    _CHUNK_SIZE = 1024 * 1024  # 1 MiB
    total_size = 0
    audio_buffer = bytearray()
    while True:
        chunk = await file.read(_CHUNK_SIZE)
        if not chunk:
            break
        total_size += len(chunk)
        if total_size > MAX_MEDIA_SIZE_BYTES:
            raise ValidationError("Media file exceeds the 50 MB size limit.", field="file")
        audio_buffer.extend(chunk)
    audio_bytes = bytes(audio_buffer)

    response = await create_media_comment(
        db=db,
        grade_id=grade_id,
        teacher_id=teacher.id,
        audio_bytes=audio_bytes,
        duration_seconds=duration_seconds,
        mime_type=mime_type,
    )
    return JSONResponse(
        status_code=201,
        content={"data": response.model_dump(mode="json")},
    )


# ---------------------------------------------------------------------------
# GET /grades/{grade_id}/media-comments
# ---------------------------------------------------------------------------


@grade_media_router.get(
    "/{grade_id}/media-comments",
    summary="List all media comments for a grade",
)
async def list_grade_media_comments_endpoint(
    grade_id: uuid.UUID,
    teacher: User = Depends(get_current_teacher),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Return all media comments for a grade in chronological order.

    Response body: ``{"data": [MediaCommentResponse, ...]}``

    Returns 403 if the grade belongs to a different teacher.
    Returns 404 if the grade does not exist.
    """
    comments = await list_grade_media_comments(
        db=db,
        grade_id=grade_id,
        teacher_id=teacher.id,
    )
    return JSONResponse(
        status_code=200,
        content={"data": [c.model_dump(mode="json") for c in comments]},
    )


# ---------------------------------------------------------------------------
# DELETE /media-comments/{media_comment_id}
# ---------------------------------------------------------------------------


@media_comments_router.delete(
    "/{media_comment_id}",
    status_code=204,
    summary="Delete a media comment and its S3 object",
)
async def delete_media_comment_endpoint(
    media_comment_id: uuid.UUID,
    teacher: User = Depends(get_current_teacher),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Delete a media comment record and remove the audio file from S3.

    Returns 204 No Content on success.
    Returns 403 if the comment belongs to a different teacher.
    Returns 404 if the comment does not exist.
    """
    await delete_media_comment(
        db=db,
        media_comment_id=media_comment_id,
        teacher_id=teacher.id,
    )
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# GET /media-comments/{media_comment_id}/url
# ---------------------------------------------------------------------------


@media_comments_router.get(
    "/{media_comment_id}/url",
    summary="Get a presigned URL for media comment playback",
)
async def get_media_comment_url_endpoint(
    media_comment_id: uuid.UUID,
    teacher: User = Depends(get_current_teacher),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Return an access-controlled pre-signed GET URL for a media comment.

    The URL is short-lived (default: ``s3_presigned_url_expire_seconds``).

    Response body: ``{"data": {"url": "https://..."}}``

    Returns 403 if the comment belongs to a different teacher.
    Returns 404 if the comment does not exist.
    """
    url_response = await get_media_comment_url(
        db=db,
        media_comment_id=media_comment_id,
        teacher_id=teacher.id,
    )
    return JSONResponse(
        status_code=200,
        content={"data": url_response.model_dump(mode="json")},
    )


# ---------------------------------------------------------------------------
# POST /media-comments/{media_comment_id}/save-to-bank
# ---------------------------------------------------------------------------


@media_comments_router.post(
    "/{media_comment_id}/save-to-bank",
    summary="Save a media comment to the teacher's reusable bank",
)
async def save_to_bank_endpoint(
    media_comment_id: uuid.UUID,
    teacher: User = Depends(get_current_teacher),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Mark a recorded media comment as a reusable bank entry.

    Once banked, the comment appears in the media comment bank picker and can be
    applied to other grades without re-recording.

    Response body: ``{"data": {"id": "...", "is_banked": true}}``

    Returns 403 if the comment belongs to a different teacher.
    Returns 404 if the comment does not exist.
    """
    result = await save_to_bank(
        db=db,
        media_comment_id=media_comment_id,
        teacher_id=teacher.id,
    )
    return JSONResponse(
        status_code=200,
        content={"data": result.model_dump(mode="json")},
    )


# ---------------------------------------------------------------------------
# GET /media-comments/bank
# ---------------------------------------------------------------------------


@media_comments_router.get(
    "/bank",
    summary="List all banked media comments for the authenticated teacher",
)
async def list_bank_endpoint(
    teacher: User = Depends(get_current_teacher),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Return all banked (reusable) media comments for the teacher, newest first.

    Response body: ``{"data": [MediaCommentResponse, ...]}``
    """
    comments = await list_banked_media_comments(
        db=db,
        teacher_id=teacher.id,
    )
    return JSONResponse(
        status_code=200,
        content={"data": [c.model_dump(mode="json") for c in comments]},
    )
