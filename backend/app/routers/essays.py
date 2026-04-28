"""Essays router — essay upload, listing, and manual assignment.

All endpoints require a valid JWT (``get_current_teacher`` dependency).
No student PII is logged — only entity IDs appear in log output.

Endpoints (``assignments_router``, prefix ``/assignments``):
  POST  /assignments/{assignmentId}/essays         — upload one or more essay files
  GET   /assignments/{assignmentId}/essays         — list essays with student info
  POST  /assignments/{assignmentId}/essays/compose — create essay for in-browser composition (M5-09)

Endpoints (``essay_router``, prefix ``/essays``):
  PATCH /essays/{essayId}                  — manually assign a student to an essay
  POST  /essays/{essayId}/grade/retry      — re-enqueue grading for a failed essay
  POST  /essays/{essayId}/snapshots        — save a writing-process snapshot (M5-09)
  GET   /essays/{essayId}/snapshots        — retrieve snapshots for editor recovery (M5-09)
  GET   /essays/{essayId}/process-signals  — composition timeline signals (M5-10)
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncGenerator

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import JSONResponse
from redis.asyncio import Redis

from app.config import settings
from app.db.session import AsyncSession, get_db
from app.dependencies import get_current_teacher
from app.exceptions import FileTooLargeError
from app.exceptions import ValidationError as DomainValidationError
from app.models.user import User
from app.schemas.batch_grading import RetryGradingRequest
from app.schemas.essay import (
    AssignEssayRequest,
    ComposeEssayRequest,
    EssayListItemResponse,
    EssayUploadItemResponse,
    WriteSnapshotRequest,
)
from app.services.batch_grading import retry_essay_grading
from app.services.essay import (
    assign_essay_to_student,
    create_composed_essay,
    get_process_signals,
    get_writing_snapshots,
    ingest_essay,
    list_essays_for_assignment,
    save_writing_snapshot,
)
from app.tasks.embedding import compute_essay_embedding as _compute_embedding_task

logger = logging.getLogger(__name__)

#: Router for assignment-scoped essay operations.
router = APIRouter(prefix="/assignments", tags=["essays"])

#: Router for essay-level operations (manual assignment, retry).
essay_router = APIRouter(prefix="/essays", tags=["essays"])


# ---------------------------------------------------------------------------
# Redis dependency — local to this router
# ---------------------------------------------------------------------------


async def _get_redis() -> AsyncGenerator[Redis, None]:  # type: ignore[type-arg]
    """FastAPI dependency that yields an async Redis client."""
    client: Redis = Redis.from_url(settings.redis_url, decode_responses=True)  # type: ignore[type-arg]
    try:
        yield client
    finally:
        await client.aclose()  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# POST /assignments/{assignmentId}/essays
# ---------------------------------------------------------------------------


@router.post(
    "/{assignment_id}/essays",
    status_code=201,
    summary="Upload one or more essay files to an assignment",
)
async def upload_essays_endpoint(
    assignment_id: uuid.UUID,
    files: list[UploadFile] = File(
        ...,
        description="One or more essay files (PDF, DOCX, or TXT)",
    ),
    student_id: uuid.UUID | None = Form(
        default=None,
        description="Optional — assign all uploaded essays to this student",
    ),
    teacher: User = Depends(get_current_teacher),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Upload one or more essay files and ingest them into an assignment.

    For each file the server:
    1. Validates MIME type server-side using python-magic (not file extension).
    2. Enforces the file size limit before reading the full file content.
    3. Stores the raw file to S3 (original preserved even on extraction failure).
    4. Extracts text: PDF via pdfplumber, DOCX via python-docx, TXT direct read.
    5. Normalizes extracted text and computes word count.
    6. Creates ``Essay`` + ``EssayVersion`` database records.

    Returns 422 if:
    - No files are provided.
    - Any file's MIME type is not allowed (PDF, DOCX, TXT only).
    - Any file exceeds the configured size limit.

    Returns 403 if the assignment belongs to a different teacher.
    Returns 404 if the assignment does not exist.
    """
    if not files:
        raise DomainValidationError("At least one file must be provided.", field="files")

    if student_id is not None and len(files) > 1:
        raise DomainValidationError(
            "Only one file may be uploaded when a student_id is provided.",
            field="files",
        )

    max_bytes = settings.max_essay_file_size_mb * 1024 * 1024
    results: list[EssayUploadItemResponse] = []

    for upload in files:
        # Read one extra byte to detect over-limit files without loading the
        # entire file into memory first.
        raw = await upload.read(max_bytes + 1)
        if len(raw) > max_bytes:
            raise FileTooLargeError(
                f"File exceeds the maximum allowed size of {settings.max_essay_file_size_mb} MB.",
                field="file",
            )

        filename = upload.filename or f"essay_{uuid.uuid4()}"

        essay, version, auto_result = await ingest_essay(
            db=db,
            teacher_id=teacher.id,
            assignment_id=assignment_id,
            filename=filename,
            data=raw,
            student_id=student_id,
        )

        # Enqueue the embedding + similarity task.  Fire-and-forget — the
        # upload response is not blocked on embedding completion.  A broker
        # outage is non-fatal: the essay is persisted and can be re-enqueued
        # manually.
        try:
            _compute_embedding_task.delay(
                str(version.id),
                str(essay.assignment_id),
                str(teacher.id),
            )
        except Exception as embed_exc:
            logger.warning(
                "Failed to enqueue embedding task — essay is still ingested",
                extra={"essay_version_id": str(version.id), "error_type": type(embed_exc).__name__},
            )

        results.append(
            EssayUploadItemResponse(
                essay_id=essay.id,
                essay_version_id=version.id,
                assignment_id=essay.assignment_id,
                student_id=essay.student_id,
                status=essay.status,
                word_count=version.word_count,
                file_storage_key=version.file_storage_key,
                submitted_at=version.submitted_at,
                auto_assign_status=auto_result.status if student_id is None else None,
            )
        )

    return JSONResponse(
        status_code=201,
        content={"data": [item.model_dump(mode="json") for item in results]},
    )


# ---------------------------------------------------------------------------
# GET /assignments/{assignmentId}/essays
# ---------------------------------------------------------------------------


@router.get(
    "/{assignment_id}/essays",
    summary="List all essays for an assignment",
    response_model=list[EssayListItemResponse],
)
async def list_essays_endpoint(
    assignment_id: uuid.UUID,
    teacher: User = Depends(get_current_teacher),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Return all essays for an assignment, including student name and status.

    Each essay carries an ``auto_assign_status`` derived from the current
    ``student_id``:

    - ``"assigned"``   — a student is assigned to the essay.
    - ``"unassigned"`` — no student is assigned yet.

    Response body: ``{"data": list[EssayListItemResponse]}``

    Returns 403 if the assignment belongs to a different teacher.
    Returns 404 if the assignment does not exist.
    """
    items = await list_essays_for_assignment(
        db=db,
        assignment_id=assignment_id,
        teacher_id=teacher.id,
    )
    return JSONResponse(
        status_code=200,
        content={"data": [item.model_dump(mode="json") for item in items]},
    )


# ---------------------------------------------------------------------------
# PATCH /essays/{essayId}
# ---------------------------------------------------------------------------


@essay_router.patch(
    "/{essay_id}",
    summary="Manually assign a student to an essay",
    response_model=EssayListItemResponse,
)
async def assign_essay_endpoint(
    essay_id: uuid.UUID,
    body: AssignEssayRequest,
    teacher: User = Depends(get_current_teacher),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Manually assign a student to an essay (auto-assignment correction).

    The student must be owned by the authenticated teacher and actively
    enrolled in the assignment's class.  The essay status is transitioned
    from ``unassigned`` → ``queued`` when it was previously unassigned.

    Response body: ``{"data": EssayListItemResponse}``

    Returns 403 if the essay belongs to a different teacher's assignment, or
    if the student is not enrolled in the assignment's class.
    Returns 404 if the essay or student does not exist.
    """
    item = await assign_essay_to_student(
        db=db,
        essay_id=essay_id,
        teacher_id=teacher.id,
        student_id=body.student_id,
    )
    return JSONResponse(
        status_code=200,
        content={"data": item.model_dump(mode="json")},
    )


# ---------------------------------------------------------------------------
# POST /essays/{essayId}/grade/retry
# ---------------------------------------------------------------------------


@essay_router.post(
    "/{essay_id}/grade/retry",
    status_code=202,
    summary="Re-enqueue grading for a failed essay",
)
async def retry_essay_grading_endpoint(
    essay_id: uuid.UUID,
    payload: RetryGradingRequest,
    teacher: User = Depends(get_current_teacher),
    db: AsyncSession = Depends(get_db),
    redis_client: Redis = Depends(_get_redis),  # type: ignore[type-arg]
) -> JSONResponse:
    """Re-enqueue grading for a single failed (reverted-to-queued) essay.

    Only available for essays with ``status=queued``.  Essays that have
    already been graded (``graded``, ``reviewed``, ``locked``, ``returned``)
    or are currently being graded (``grading``) return 409.

    Returns 202 immediately — does not wait for the task to complete.

    Returns 403 if the essay belongs to a different teacher.
    Returns 404 if the essay does not exist.
    Returns 409 if the essay is not in a retryable state.
    """
    await retry_essay_grading(
        db=db,
        redis=redis_client,
        essay_id=essay_id,
        teacher_id=teacher.id,
        strictness=payload.strictness,
    )
    return JSONResponse(
        status_code=202,
        content={"data": {"essay_id": str(essay_id), "status": "queued"}},
    )


# ---------------------------------------------------------------------------
# POST /assignments/{assignmentId}/essays/compose  (M5-09)
# ---------------------------------------------------------------------------


@router.post(
    "/{assignment_id}/essays/compose",
    status_code=201,
    summary="Create a blank essay for in-browser composition",
)
async def compose_essay_endpoint(
    assignment_id: uuid.UUID,
    body: ComposeEssayRequest,
    teacher: User = Depends(get_current_teacher),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Create an empty essay version ready for in-browser rich-text composition.

    Unlike the file-upload endpoint, no file is provided.  The server creates
    an :class:`~app.models.essay.Essay` record with status ``unassigned`` (or
    ``queued`` when ``student_id`` is supplied) and an empty
    :class:`~app.models.essay.EssayVersion` with ``writing_snapshots = []``.

    The client then uses ``POST /essays/{essayId}/snapshots`` to persist
    autosaved content and ``GET /essays/{essayId}/snapshots`` to recover the
    editor state after a refresh.

    Response body: ``{"data": ComposeEssayResponse}``

    Returns 403 if the assignment belongs to a different teacher, or if the
    supplied ``student_id`` is not enrolled in the assignment's class.
    Returns 404 if the assignment (or supplied student) does not exist.
    """
    result = await create_composed_essay(
        db=db,
        teacher_id=teacher.id,
        assignment_id=assignment_id,
        student_id=body.student_id,
    )
    return JSONResponse(
        status_code=201,
        content={"data": result.model_dump(mode="json")},
    )


# ---------------------------------------------------------------------------
# POST /essays/{essayId}/snapshots  (M5-09)
# ---------------------------------------------------------------------------


@essay_router.post(
    "/{essay_id}/snapshots",
    status_code=200,
    summary="Save a writing-process snapshot (autosave)",
)
async def save_snapshot_endpoint(
    essay_id: uuid.UUID,
    body: WriteSnapshotRequest,
    teacher: User = Depends(get_current_teacher),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Append a writing-process snapshot to the essay version.

    Called by the browser writing interface on each debounced autosave tick
    (every 10–15 seconds of activity).  The ``html_content`` is the raw
    innerHTML of the rich-text editor; ``word_count`` is pre-computed by the
    client (HTML tags stripped, split on whitespace).

    The server:
    1. Verifies the essay belongs to the authenticated teacher.
    2. Strips HTML tags to derive a grading-compatible plain-text ``content``.
    3. Appends a snapshot record to ``writing_snapshots`` JSONB.
    4. Updates ``EssayVersion.content`` and ``word_count``.

    Response body: ``{"data": WriteSnapshotResponse}``

    Returns 403 if the essay belongs to a different teacher.
    Returns 404 if the essay or its version does not exist.

    Security: no essay content or student PII appears in log output; only
    entity IDs (``essay_id``, ``essay_version_id``) are logged.
    """
    result = await save_writing_snapshot(
        db=db,
        teacher_id=teacher.id,
        essay_id=essay_id,
        html_content=body.html_content,
        word_count=body.word_count,
    )
    return JSONResponse(
        status_code=200,
        content={"data": result.model_dump(mode="json")},
    )


# ---------------------------------------------------------------------------
# GET /essays/{essayId}/snapshots  (M5-09)
# ---------------------------------------------------------------------------


@essay_router.get(
    "/{essay_id}/snapshots",
    summary="Retrieve writing snapshots for editor state recovery",
)
async def get_snapshots_endpoint(
    essay_id: uuid.UUID,
    teacher: User = Depends(get_current_teacher),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Return the current HTML content and snapshot metadata for a browser-composed essay.

    The browser writing interface calls this endpoint on mount to restore
    the editor state after a page refresh or navigation event.

    The response includes:
    - ``current_content``: the latest snapshot's ``html_content`` (ready to
      inject into the editor's ``innerHTML``).
    - ``word_count``: current word count.
    - ``snapshots``: lightweight metadata (seq, ts, word_count) for the full
      snapshot history.  Individual ``html_content`` values of earlier
      snapshots are not returned in this response.

    Response body: ``{"data": GetSnapshotsResponse}``

    Returns 403 if the essay belongs to a different teacher.
    Returns 404 if the essay or its version does not exist.
    """
    result = await get_writing_snapshots(
        db=db,
        teacher_id=teacher.id,
        essay_id=essay_id,
    )
    return JSONResponse(
        status_code=200,
        content={"data": result.model_dump(mode="json")},
    )


# ---------------------------------------------------------------------------
# GET /essays/{essayId}/process-signals  (M5-10)
# ---------------------------------------------------------------------------


@essay_router.get(
    "/{essay_id}/process-signals",
    summary="Get composition timeline and process signals for a browser-composed essay",
)
async def get_process_signals_endpoint(
    essay_id: uuid.UUID,
    teacher: User = Depends(get_current_teacher),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Return composition timeline signals derived from the writing-process snapshots.

    Signals are computed lazily on first request and cached in the database.
    If the snapshot history has grown since the last computation the cache is
    automatically invalidated and re-computed.

    The response includes:

    - ``sessions`` — list of contiguous writing sessions with start/end times
      and word-count data.
    - ``paste_events`` — snapshot steps where the word count jumped by a large
      amount in a single autosave tick (potential paste-from-clipboard signal).
    - ``rapid_completion_events`` — sessions where a large fraction of the
      final essay was written in a short time window.
    - Summary metrics: ``session_count``, ``active_writing_seconds``,
      ``total_elapsed_seconds``, ``inter_session_gaps_seconds``.

    When ``has_process_data`` is ``false`` the essay was submitted as a file
    upload (no writing-process data captured).  All list fields are empty and
    numeric metrics are zero.  This is not an error — the frontend should
    surface a plain-language explanation to the teacher.

    Response body: ``{"data": ProcessSignalsResponse}``

    Returns 403 if the essay belongs to a different teacher.
    Returns 404 if the essay or its version does not exist.

    Security: no essay content or student PII appears in log output.
    """
    result = await get_process_signals(
        db=db,
        teacher_id=teacher.id,
        essay_id=essay_id,
    )
    return JSONResponse(
        status_code=200,
        content={"data": result.model_dump(mode="json")},
    )
