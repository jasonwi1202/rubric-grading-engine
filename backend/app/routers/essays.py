"""Essays router — essay upload endpoint.

All endpoints require a valid JWT (``get_current_teacher`` dependency).
No student PII is logged — only entity IDs appear in log output.

Endpoints:
  POST /assignments/{assignmentId}/essays — upload one or more essay files
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import JSONResponse

from app.config import settings
from app.db.session import AsyncSession, get_db
from app.dependencies import get_current_teacher
from app.exceptions import FileTooLargeError
from app.exceptions import ValidationError as DomainValidationError
from app.models.user import User
from app.schemas.essay import EssayUploadItemResponse
from app.services.essay import ingest_essay

router = APIRouter(prefix="/assignments", tags=["essays"])


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

        essay, version = await ingest_essay(
            db=db,
            teacher_id=teacher.id,
            assignment_id=assignment_id,
            filename=filename,
            data=raw,
            student_id=student_id,
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
            )
        )

    return JSONResponse(
        status_code=201,
        content={"data": [item.model_dump(mode="json") for item in results]},
    )
