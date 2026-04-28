"""Essay ingestion service.

Handles file validation, S3 storage, text extraction, normalization, and
database record creation for uploaded essay files.

Pipeline:
  1. Validate file size (``settings.max_essay_file_size_mb``)
  2. Validate MIME type server-side using ``python-magic``
  3. Verify assignment ownership (teacher_id)
  4. Validate explicit student_id enrollment (when provided)
  5. Create ``Essay`` DB record early so its UUID is available for the S3 key
  6. Upload raw bytes to S3 (before any extraction attempt)
  7. Extract text: PDF → pdfplumber, DOCX → python-docx, TXT → direct read
     On failure the S3 object is deleted to avoid orphaned storage objects.
  8. Normalize extracted text (whitespace, Unicode, non-printable chars)
  9. Attempt student auto-assignment (fuzzy match against class roster)
  10. Create ``EssayVersion`` database record and commit

No student PII is logged at any point — only entity IDs appear in log output.
"""

from __future__ import annotations

import asyncio
import html as _html_module
import io
import logging
import os
import re
import unicodedata
import uuid
from datetime import UTC, datetime
from html.parser import HTMLParser as _HtmlParser
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.exceptions import (
    FileTooLargeError,
    FileTypeNotAllowedError,
    ForbiddenError,
    NotFoundError,
    ValidationError,
)
from app.models.assignment import Assignment
from app.models.class_ import Class
from app.models.class_enrollment import ClassEnrollment
from app.models.essay import Essay, EssayStatus, EssayVersion
from app.models.student import Student
from app.schemas.essay import AutoAssignStatus as AutoAssignStatusType
from app.schemas.essay import (
    ComposeEssayResponse,
    EssayListItemResponse,
    GetSnapshotsResponse,
    PasteEventResponse,
    ProcessSignalsResponse,
    RapidCompletionEventResponse,
    SessionSegmentResponse,
    SnapshotItem,
    WriteSnapshotResponse,
)
from app.services.composition_timeline import analyze_writing_process
from app.services.student_matching import HEADER_CHAR_LIMIT, AutoAssignResult, match_student
from app.storage.s3 import delete_file, upload_file

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ALLOWED_MIME_TYPES: frozenset[str] = frozenset(
    {
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "text/plain",
    }
)

# Minimum extracted word count below which we flag the version as potentially
# a poor extraction (e.g. image-only PDF).
_MIN_WORD_COUNT_THRESHOLD = 50

# Maximum length of the sanitized filename component used in S3 keys and stored
# in EssayVersion.file_storage_key (String(500)).  The fixed prefix
# ``essays/{uuid}/{uuid}/`` consumes 81 chars; 200 leaves a comfortable margin.
_MAX_FILENAME_LENGTH = 200


# ---------------------------------------------------------------------------
# Internal helpers — filename sanitization
# ---------------------------------------------------------------------------


def _sanitize_filename(filename: str) -> str:
    """Return a safe version of *filename* for use in S3 object keys.

    - Takes only the basename to strip any directory-traversal sequences.
    - Replaces every character that is not alphanumeric, dot, hyphen, or
      underscore with an underscore.
    - Truncates to :data:`_MAX_FILENAME_LENGTH` characters to prevent
      ``EssayVersion.file_storage_key`` (``String(500)``) overflow.
    - Falls back to a UUID-based name if the sanitized result is empty.
    """
    name = os.path.basename(filename)
    name = re.sub(r"[^A-Za-z0-9._\-]", "_", name)
    name = name[:_MAX_FILENAME_LENGTH]
    return name or f"essay_{uuid.uuid4()}"


# ---------------------------------------------------------------------------
# Internal helpers — text extraction
# ---------------------------------------------------------------------------


def _detect_mime_type(data: bytes) -> str:
    """Return the MIME type of *data* detected server-side via ``python-magic``.

    Does **not** trust the ``Content-Type`` header or file extension — the
    MIME type is computed from the file's magic bytes.
    """
    import magic  # noqa: PLC0415 — defer import; magic is always installed

    return magic.from_buffer(data, mime=True)


def _extract_text_pdf(data: bytes) -> str:
    """Extract plain text from a PDF file using ``pdfplumber``.

    Concatenates text from all pages with a single newline separator.
    Returns an empty string if pdfplumber finds no text (e.g. image-only PDF).
    """
    import pdfplumber  # noqa: PLC0415 — defer import

    pages: list[str] = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            pages.append(text)
    return "\n".join(pages)


def _extract_text_docx(data: bytes) -> str:
    """Extract plain text from a DOCX file using ``python-docx``.

    Joins all non-empty paragraphs with a newline.
    """
    from docx import Document  # noqa: PLC0415 — defer import

    doc = Document(io.BytesIO(data))
    return "\n".join(para.text for para in doc.paragraphs if para.text)


def _extract_text_txt(data: bytes) -> str:
    """Decode a plain-text file as UTF-8 (falling back to latin-1)."""
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def extract_text(data: bytes, mime_type: str) -> str:
    """Dispatch text extraction to the appropriate extractor by MIME type.

    Args:
        data: Raw file bytes.
        mime_type: Validated MIME type string (one of :data:`ALLOWED_MIME_TYPES`).

    Returns:
        Raw extracted text (un-normalized).

    Raises:
        FileTypeNotAllowedError: If ``mime_type`` is not in the allowed set.
    """
    if mime_type == "application/pdf":
        return _extract_text_pdf(data)
    if mime_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        return _extract_text_docx(data)
    if mime_type == "text/plain":
        return _extract_text_txt(data)
    raise FileTypeNotAllowedError(
        f"Unsupported MIME type for extraction: {mime_type}", field="file"
    )


# ---------------------------------------------------------------------------
# Internal helpers — normalization
# ---------------------------------------------------------------------------


def normalize_text(text: str) -> str:
    """Normalize extracted essay text.

    Steps applied in order:
    1. NFC Unicode normalization (canonical decomposition → composition).
    2. Remove non-printable characters (except newlines and tabs).
    3. Collapse runs of blank lines (more than two consecutive newlines → two).
    4. Strip leading/trailing whitespace from each line.
    5. Strip leading/trailing whitespace from the whole string.

    The result is stored verbatim as plain text — it is **never executed**.
    """
    # 1. NFC normalization.
    text = unicodedata.normalize("NFC", text)

    # 2. Remove non-printable characters, preserving newlines (\n) and
    #    horizontal tabs (\t) which carry structural meaning in some files.
    text = "".join(
        ch for ch in text if ch in ("\n", "\t") or not unicodedata.category(ch).startswith("C")
    )

    # 3. Strip leading/trailing whitespace from each line.
    lines = [line.rstrip() for line in text.splitlines()]
    text = "\n".join(lines)

    # 4. Collapse runs of three or more consecutive blank lines to two.
    text = re.sub(r"\n{3,}", "\n\n", text)

    # 5. Strip the whole string.
    return text.strip()


def count_words(text: str) -> int:
    """Return the number of whitespace-delimited tokens in *text*."""
    return len(text.split())


# ---------------------------------------------------------------------------
# Internal helpers — validation
# ---------------------------------------------------------------------------


def validate_file_size(data: bytes) -> None:
    """Raise :exc:`FileTooLargeError` if *data* exceeds the configured limit.

    The limit is read from ``settings.max_essay_file_size_mb``.
    """
    max_bytes = settings.max_essay_file_size_mb * 1024 * 1024
    if len(data) > max_bytes:
        raise FileTooLargeError(
            f"File exceeds the maximum allowed size of {settings.max_essay_file_size_mb} MB.",
            field="file",
        )


def validate_mime_type(data: bytes) -> str:
    """Detect the MIME type of *data* and raise if it is not allowed.

    Returns the detected MIME type string on success.

    Raises:
        FileTypeNotAllowedError: If the MIME type is not in
            :data:`ALLOWED_MIME_TYPES`.
    """
    mime_type = _detect_mime_type(data)
    if mime_type not in ALLOWED_MIME_TYPES:
        raise FileTypeNotAllowedError(
            f"File type '{mime_type}' is not allowed. "
            "Only PDF, DOCX, and plain-text files are accepted.",
            field="file",
        )
    return mime_type


# ---------------------------------------------------------------------------
# Internal helpers — assignment ownership
# ---------------------------------------------------------------------------


async def _get_assignment_for_teacher(
    db: AsyncSession,
    assignment_id: uuid.UUID,
    teacher_id: uuid.UUID,
) -> Assignment:
    """Return the Assignment if it exists and is owned by *teacher_id*.

    Raises:
        NotFoundError: Assignment does not exist.
        ForbiddenError: Assignment belongs to a different teacher.
    """
    # Two-step ownership check: first confirm existence, then check teacher.
    ownership_result = await db.execute(
        select(Assignment.id, Class.teacher_id)
        .join(Class, Assignment.class_id == Class.id)
        .where(Assignment.id == assignment_id)
    )
    row = ownership_result.one_or_none()
    if row is None:
        raise NotFoundError("Assignment not found.")
    if row.teacher_id != teacher_id:
        raise ForbiddenError("You do not have access to this assignment.")

    result = await db.execute(
        select(Assignment)
        .join(Class, Assignment.class_id == Class.id)
        .where(Assignment.id == assignment_id, Class.teacher_id == teacher_id)
    )
    assignment = result.scalar_one_or_none()
    if assignment is None:
        raise NotFoundError("Assignment not found.")
    return assignment


def _extract_docx_author(data: bytes) -> str | None:
    """Return the author from a DOCX file's core properties, or ``None``.

    Reads ``docProps/core.xml`` directly from the ZIP archive instead of
    building a full ``python-docx`` Document object, so the bytes are only
    parsed once (text extraction already called ``_extract_text_docx``).

    Extraction failure is non-fatal — if the author field is absent or
    the file cannot be parsed here, ``None`` is returned silently.

    The returned value is used only as a fuzzy-matching signal and is
    **never logged**.
    """
    import xml.etree.ElementTree as ET  # noqa: PLC0415 — defer import
    import zipfile  # noqa: PLC0415 — defer import

    try:
        with zipfile.ZipFile(io.BytesIO(data)) as docx_zip:
            core_xml = docx_zip.read("docProps/core.xml")
        root = ET.fromstring(core_xml)
        author = root.findtext(
            "dc:creator",
            default="",
            namespaces={"dc": "http://purl.org/dc/elements/1.1/"},
        )
        return (author or "").strip() or None
    except Exception:  # noqa: BLE001 — any parse error is non-fatal
        return None


async def _load_class_roster(
    db: AsyncSession,
    class_id: uuid.UUID,
    teacher_id: uuid.UUID,
) -> list[tuple[uuid.UUID, str]]:
    """Return ``(student_id, full_name)`` pairs for all actively enrolled students.

    Only students owned by *teacher_id* and currently enrolled (``removed_at
    IS NULL``) in *class_id* are returned.

    Returns an empty list when the class has no enrolled students.

    No student PII is logged here or by callers — only entity IDs appear in
    log output.
    """
    result = await db.execute(
        select(Student.id, Student.full_name)
        .join(ClassEnrollment, Student.id == ClassEnrollment.student_id)
        .where(
            ClassEnrollment.class_id == class_id,
            ClassEnrollment.removed_at.is_(None),
            Student.teacher_id == teacher_id,
        )
    )
    return [(row.id, row.full_name) for row in result.all()]


async def _validate_student_for_assignment(
    db: AsyncSession,
    student_id: uuid.UUID,
    teacher_id: uuid.UUID,
    class_id: uuid.UUID,
) -> None:
    """Verify *student_id* is owned by *teacher_id* and enrolled in *class_id*.

    Raises:
        NotFoundError: Student does not exist or does not belong to *teacher_id*.
        ForbiddenError: Student is not actively enrolled in the assignment's class.
    """
    student_result = await db.execute(
        select(Student.id).where(
            Student.id == student_id,
            Student.teacher_id == teacher_id,
        )
    )
    if student_result.scalar_one_or_none() is None:
        logger.debug(
            "Student not found for teacher during essay ingest",
            extra={"student_id": str(student_id), "teacher_id": str(teacher_id)},
        )
        raise NotFoundError("Student not found.")

    enrollment_result = await db.execute(
        select(ClassEnrollment.id).where(
            ClassEnrollment.student_id == student_id,
            ClassEnrollment.class_id == class_id,
            ClassEnrollment.removed_at.is_(None),
        )
    )
    if enrollment_result.scalar_one_or_none() is None:
        raise ForbiddenError("Student is not enrolled in this assignment's class.")


# ---------------------------------------------------------------------------
# Public service function
# ---------------------------------------------------------------------------


async def ingest_essay(
    db: AsyncSession,
    teacher_id: uuid.UUID,
    assignment_id: uuid.UUID,
    filename: str,
    data: bytes,
    student_id: uuid.UUID | None = None,
) -> tuple[Essay, EssayVersion, AutoAssignResult]:
    """Validate, store, extract, and persist a single uploaded essay file.

    Args:
        db: Async database session.
        teacher_id: The authenticated teacher's UUID (used for tenant scoping).
        assignment_id: Target assignment UUID.
        filename: Original filename from the upload (sanitized server-side before
            use — never logged or executed).
        data: Raw file bytes read from the upload.
        student_id: Optional — if provided, the essay is immediately assigned to
            this student.  The student must be owned by *teacher_id* and
            actively enrolled in the assignment's class.  Skips auto-assignment.

    Returns:
        A ``(Essay, EssayVersion, AutoAssignResult)`` triple.

        *  ``Essay`` — the newly created essay record (``student_id`` and
           ``status`` already reflect the auto-assignment outcome).
        *  ``EssayVersion`` — version 1 of the essay.
        *  ``AutoAssignResult`` — detailed outcome of the auto-assignment
           attempt.  When *student_id* was explicitly provided the result
           has ``status="assigned"`` with ``match_count=0`` (no roster search
           was performed).

    Raises:
        FileTooLargeError: File exceeds ``settings.max_essay_file_size_mb``.
        FileTypeNotAllowedError: MIME type is not allowed.
        NotFoundError: Assignment does not exist, or *student_id* is provided
            but the student is not found for this teacher.
        ForbiddenError: Assignment belongs to a different teacher, or
            *student_id* is provided but the student is not enrolled in the
            assignment's class.

    Security notes:
        - MIME type is validated from magic bytes, **not** the file extension.
        - File size is checked before any extraction attempt.
        - The raw file is uploaded to S3 **before** extraction so the original
          bytes are preserved.  If extraction subsequently fails, the S3 object
          is deleted to avoid leaving orphaned storage objects with no matching
          DB record.
        - The client-supplied filename is sanitized (basename only, safe chars,
          length capped) before being embedded in the S3 key.
        - Extracted text is stored as a plain string — it is never executed.
        - No student PII appears in any log output.
    """
    # 1. Validate file size (fast path — before any extraction or S3 I/O).
    validate_file_size(data)

    # 2. Detect and validate MIME type from magic bytes (not file extension).
    mime_type = validate_mime_type(data)

    # 3. Verify the assignment exists and belongs to this teacher.
    assignment = await _get_assignment_for_teacher(db, assignment_id, teacher_id)

    # 4. If a student_id was supplied, verify ownership and enrollment.
    if student_id is not None:
        await _validate_student_for_assignment(db, student_id, teacher_id, assignment.class_id)

    # 5. Create the Essay record (status unassigned until auto-assign runs).
    essay = Essay(
        assignment_id=assignment.id,
        student_id=student_id,
        status=EssayStatus.unassigned if student_id is None else EssayStatus.queued,
    )
    db.add(essay)
    await db.flush()  # populate essay.id

    # 6. Upload the raw file to S3 before any extraction attempt.
    #    Sanitize the filename to prevent path-traversal and DB column overflow.
    #    upload_file is synchronous (boto3); run it in a thread-pool executor
    #    so it does not block the event loop.
    safe_filename = _sanitize_filename(filename)
    s3_key = f"essays/{assignment.id}/{essay.id}/{safe_filename}"
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, upload_file, s3_key, data, mime_type)
    logger.info(
        "Essay file uploaded to S3",
        extra={"essay_id": str(essay.id), "assignment_id": str(assignment.id)},
    )

    # 7. Extract text.  On failure, clean up the uploaded S3 object so we don't
    #    leave orphaned objects with no matching DB record, then re-raise.
    try:
        raw_text = extract_text(data, mime_type)
    except Exception:
        logger.exception(
            "Text extraction failed; cleaning up S3 object",
            extra={"essay_id": str(essay.id), "s3_key": s3_key},
        )
        try:
            await loop.run_in_executor(None, delete_file, s3_key)
        except Exception:
            logger.exception(
                "S3 cleanup after extraction failure also failed",
                extra={"essay_id": str(essay.id), "s3_key": s3_key},
            )
        raise

    # 8. Normalize extracted text.
    normalized = normalize_text(raw_text)
    words = count_words(normalized)

    if words < _MIN_WORD_COUNT_THRESHOLD:
        logger.warning(
            "Extracted text is suspiciously short",
            extra={"essay_id": str(essay.id), "word_count": words, "mime_type": mime_type},
        )

    # 9. Attempt student auto-assignment when no student_id was explicitly
    #    supplied.  The roster is loaded fresh for every call so that any
    #    concurrent enrollment changes are reflected.
    auto_result: AutoAssignResult
    if student_id is None:
        roster = await _load_class_roster(db, assignment.class_id, teacher_id)

        # Extract DOCX author from core properties when the file is a DOCX.
        docx_author: str | None = None
        if mime_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
            docx_author = _extract_docx_author(data)

        # Use the first HEADER_CHAR_LIMIT characters as the header signal.
        header_text = normalized[:HEADER_CHAR_LIMIT]

        auto_result = match_student(
            roster=roster,
            filename=filename,
            docx_author=docx_author,
            header_text=header_text,
        )

        if auto_result.status == "assigned":
            essay.student_id = auto_result.student_id
            essay.status = EssayStatus.queued
            logger.info(
                "Essay auto-assigned to student",
                extra={
                    "essay_id": str(essay.id),
                    "signal": auto_result.candidates[0].signal,
                    "confidence": round(auto_result.candidates[0].confidence, 4),
                },
            )
        elif auto_result.status == "ambiguous":
            logger.info(
                "Essay auto-assignment ambiguous — held for manual review",
                extra={
                    "essay_id": str(essay.id),
                    "match_count": auto_result.match_count,
                },
            )
        else:
            logger.info(
                "Essay auto-assignment found no match — held for manual review",
                extra={"essay_id": str(essay.id)},
            )
    else:
        # student_id was explicitly provided — no roster search was performed.
        auto_result = AutoAssignResult(
            status="assigned",
            student_id=student_id,
            match_count=0,
        )

    # 10. Create EssayVersion record (version 1 = original submission).
    version = EssayVersion(
        essay_id=essay.id,
        version_number=1,
        content=normalized,
        file_storage_key=s3_key,
        word_count=words,
    )
    db.add(version)

    await db.commit()
    await db.refresh(essay)
    await db.refresh(version)

    logger.info(
        "Essay ingested",
        extra={
            "essay_id": str(essay.id),
            "essay_version_id": str(version.id),
            "assignment_id": str(assignment.id),
            "word_count": words,
        },
    )
    return essay, version, auto_result


# ---------------------------------------------------------------------------
# Public service functions — list and manual assignment
# ---------------------------------------------------------------------------


async def _get_essay_for_teacher(
    db: AsyncSession,
    essay_id: uuid.UUID,
    teacher_id: uuid.UUID,
) -> Essay:
    """Return the Essay if it exists and the parent assignment belongs to *teacher_id*.

    Two-step ownership check: 404 when the essay is not found at all;
    403 when it exists but belongs to a different teacher's assignment.

    Raises:
        NotFoundError: Essay does not exist.
        ForbiddenError: Essay belongs to a different teacher's assignment.
    """
    check_result = await db.execute(
        select(Essay.id, Class.teacher_id)
        .join(Assignment, Essay.assignment_id == Assignment.id)
        .join(Class, Assignment.class_id == Class.id)
        .where(Essay.id == essay_id)
    )
    row = check_result.one_or_none()
    if row is None:
        raise NotFoundError("Essay not found.")
    if row.teacher_id != teacher_id:
        raise ForbiddenError("You do not have access to this essay.")

    essay_result = await db.execute(select(Essay).where(Essay.id == essay_id))
    return essay_result.scalar_one()


async def list_essays_for_assignment(
    db: AsyncSession,
    assignment_id: uuid.UUID,
    teacher_id: uuid.UUID,
) -> list[EssayListItemResponse]:
    """Return all essays for an assignment, scoped to *teacher_id*.

    Each item includes the student name (if assigned) and an
    ``auto_assign_status`` derived from whether a student is currently
    assigned:

    - ``"assigned"``   — ``student_id`` is not null.
    - ``"unassigned"`` — ``student_id`` is null.

    The original "ambiguous" state is not persisted after the upload
    response; essays that were formerly ambiguous appear here as
    ``"unassigned"`` until the teacher manually assigns them.

    Raises:
        NotFoundError:  Assignment does not exist.
        ForbiddenError: Assignment belongs to a different teacher.

    No student PII appears in any log output.
    """
    await _get_assignment_for_teacher(db, assignment_id, teacher_id)

    # Subquery: latest version number per essay.
    latest_ver_sq = (
        select(
            EssayVersion.essay_id,
            func.max(EssayVersion.version_number).label("max_ver"),
        )
        .group_by(EssayVersion.essay_id)
        .subquery("latest_ver_sq")
    )

    result = await db.execute(
        select(
            Essay.id.label("essay_id"),
            Essay.assignment_id,
            Essay.student_id,
            Essay.status,
            Essay.created_at,
            EssayVersion.word_count,
            EssayVersion.submitted_at,
            Student.full_name.label("student_name"),
        )
        .join(latest_ver_sq, Essay.id == latest_ver_sq.c.essay_id)
        .join(
            EssayVersion,
            (Essay.id == EssayVersion.essay_id)
            & (EssayVersion.version_number == latest_ver_sq.c.max_ver),
        )
        .outerjoin(
            Student,
            (Essay.student_id == Student.id) & (Student.teacher_id == teacher_id),
        )
        .where(Essay.assignment_id == assignment_id)
        .order_by(Essay.created_at)
    )

    items: list[EssayListItemResponse] = []
    for row in result.all():
        auto_assign_status: AutoAssignStatusType = (
            "assigned" if row.student_id is not None else "unassigned"
        )
        items.append(
            EssayListItemResponse(
                essay_id=row.essay_id,
                assignment_id=row.assignment_id,
                student_id=row.student_id,
                student_name=row.student_name,
                status=row.status,
                word_count=row.word_count,
                submitted_at=row.submitted_at,
                auto_assign_status=auto_assign_status,
            )
        )
    return items


async def assign_essay_to_student(
    db: AsyncSession,
    essay_id: uuid.UUID,
    teacher_id: uuid.UUID,
    student_id: uuid.UUID,
) -> EssayListItemResponse:
    """Manually assign a student to an essay (manual-correction step).

    Validates that *student_id* belongs to *teacher_id* and is actively
    enrolled in the assignment's class.  Updates ``essay.student_id`` and
    transitions the essay status from ``unassigned`` → ``queued`` when it
    was previously unassigned.

    Returns an :class:`~app.schemas.essay.EssayListItemResponse` reflecting
    the updated state.

    Raises:
        NotFoundError:  Essay or student not found.
        ForbiddenError: Essay belongs to a different teacher, or the student
            is not enrolled in the assignment's class.

    No student PII appears in any log output.
    """
    essay = await _get_essay_for_teacher(db, essay_id, teacher_id)

    # Load the assignment to obtain class_id for enrollment validation.
    assignment_result = await db.execute(
        select(Assignment).where(Assignment.id == essay.assignment_id)
    )
    assignment = assignment_result.scalar_one_or_none()
    if assignment is None:
        raise NotFoundError("Assignment not found.")  # FK constraint broken otherwise

    await _validate_student_for_assignment(db, student_id, teacher_id, assignment.class_id)

    # Fetch student name for the response (never logged).
    student_result = await db.execute(select(Student.full_name).where(Student.id == student_id))
    student_name: str | None = student_result.scalar_one_or_none()
    # _validate_student_for_assignment already confirmed existence; this guards
    # against a race condition where the student was deleted between validation
    # and the name fetch.
    if student_name is None:
        raise NotFoundError("Student not found.")

    essay.student_id = student_id
    if essay.status == EssayStatus.unassigned:
        essay.status = EssayStatus.queued

    await db.flush()

    # Fetch the latest essay version for word_count / submitted_at.
    version_result = await db.execute(
        select(EssayVersion)
        .where(EssayVersion.essay_id == essay_id)
        .order_by(EssayVersion.version_number.desc())
        .limit(1)
    )
    version = version_result.scalar_one()

    await db.commit()

    logger.info(
        "Essay manually assigned to student",
        extra={"essay_id": str(essay_id)},
    )

    return EssayListItemResponse(
        essay_id=essay.id,
        assignment_id=essay.assignment_id,
        student_id=essay.student_id,
        student_name=student_name,
        status=essay.status,
        word_count=version.word_count,
        submitted_at=version.submitted_at,
        auto_assign_status="assigned",
    )


# ---------------------------------------------------------------------------
# Browser composition — M5-09
# ---------------------------------------------------------------------------


def _strip_html_tags(html_content: str) -> str:
    """Return plain text by stripping all HTML tags and decoding entities.

    Used to derive a grading-compatible plain-text ``content`` value from the
    browser editor's innerHTML.  The result is never executed — it is stored
    and used only as plain-text input to the LLM grading pipeline.
    """
    # Replace block-level tags with newlines to preserve paragraph structure.
    html_content = re.sub(r"<(br|p|div|li|h[1-6])[^>]*>", "\n", html_content, flags=re.IGNORECASE)
    # Strip all remaining tags.
    text = re.sub(r"<[^>]+>", "", html_content)
    # Decode HTML entities (e.g. &amp; → &, &nbsp; → space).
    text = _html_module.unescape(text)
    return normalize_text(text)


class _SafeHtmlFilter(_HtmlParser):
    """Whitelist-based HTML sanitizer for browser-composed essay content.

    Retains only a safe subset of formatting tags (bold, italic, underline,
    paragraph, div, span, br) with **no attributes**.  All other tags are
    removed; their text content is preserved but HTML-escaped to prevent
    injection if the tag itself is disallowed.

    This is a defence-in-depth measure: the frontend already sanitises before
    sending, but the server should not trust client-supplied HTML unconditionally.
    """

    _ALLOWED_TAGS: frozenset[str] = frozenset(
        {"p", "b", "i", "u", "em", "strong", "br", "span", "div"}
    )
    # Void elements that have no closing tag.
    _VOID_TAGS: frozenset[str] = frozenset({"br"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._buf: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._ALLOWED_TAGS:
            self._buf.append(f"<{tag}>")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._ALLOWED_TAGS and tag not in self._VOID_TAGS:
            self._buf.append(f"</{tag}>")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        # Self-closing tags (e.g. <br/>).
        if tag in self._ALLOWED_TAGS:
            self._buf.append(f"<{tag}>")

    def handle_data(self, data: str) -> None:
        # Escape all text data to prevent injection of disallowed markup.
        self._buf.append(_html_module.escape(data))

    def get_output(self) -> str:
        return "".join(self._buf)


def _sanitize_html_content(html_content: str) -> str:
    """Strip disallowed tags and attributes from HTML before persisting.

    Only the tags in ``_SafeHtmlFilter._ALLOWED_TAGS`` are preserved, with no
    attributes.  This prevents stored-XSS when the sanitised HTML is later
    re-injected into the teacher's editor via ``innerHTML``.
    """
    filt = _SafeHtmlFilter()
    try:
        filt.feed(html_content)
    finally:
        # close() must be called in a finally block so the parser is finalised
        # even if feed() raises (e.g. on deeply malformed HTML).  Without close(),
        # any content buffered by HTMLParser's internal state machine is never
        # flushed to _buf, producing truncated output.
        filt.close()
    return filt.get_output()


async def create_composed_essay(
    db: AsyncSession,
    teacher_id: uuid.UUID,
    assignment_id: uuid.UUID,
    student_id: uuid.UUID | None = None,
) -> ComposeEssayResponse:
    """Create an empty essay version for in-browser composition.

    Equivalent to starting a blank document — no file upload or text extraction
    is performed.  The essay version is created with empty ``content`` and an
    empty ``writing_snapshots`` list so subsequent snapshot saves can append
    to it.

    Args:
        db: Async database session.
        teacher_id: The authenticated teacher's UUID (tenant scoping).
        assignment_id: Target assignment UUID.
        student_id: Optional — if provided, the essay is immediately assigned
            to this student.  The student must be owned by *teacher_id* and
            actively enrolled in the assignment's class.

    Returns:
        A :class:`~app.schemas.essay.ComposeEssayResponse` with the new essay
        and version IDs.

    Raises:
        NotFoundError:  Assignment does not exist, or *student_id* is provided
            but the student is not found for this teacher.
        ForbiddenError: Assignment belongs to a different teacher, or
            *student_id* is provided but the student is not enrolled.

    No student PII appears in any log output.
    """
    assignment = await _get_assignment_for_teacher(db, assignment_id, teacher_id)

    if student_id is not None:
        await _validate_student_for_assignment(db, student_id, teacher_id, assignment.class_id)

    essay = Essay(
        assignment_id=assignment.id,
        student_id=student_id,
        status=EssayStatus.unassigned if student_id is None else EssayStatus.queued,
    )
    db.add(essay)
    await db.flush()  # populate essay.id

    version = EssayVersion(
        essay_id=essay.id,
        version_number=1,
        content="",
        file_storage_key=None,
        word_count=0,
        writing_snapshots=[],  # empty list signals browser-composed essay
    )
    db.add(version)

    await db.commit()
    await db.refresh(essay)
    await db.refresh(version)

    logger.info(
        "Browser-composed essay created",
        extra={
            "essay_id": str(essay.id),
            "essay_version_id": str(version.id),
            "assignment_id": str(assignment.id),
        },
    )

    return ComposeEssayResponse(
        essay_id=essay.id,
        essay_version_id=version.id,
        assignment_id=essay.assignment_id,
        student_id=essay.student_id,
        status=essay.status,
        current_content="",
        word_count=0,
    )


async def save_writing_snapshot(
    db: AsyncSession,
    teacher_id: uuid.UUID,
    essay_id: uuid.UUID,
    html_content: str,
    word_count: int,
) -> WriteSnapshotResponse:
    """Append a writing-process snapshot to the essay version and update content.

    Called by the browser autosave on each debounce tick.  Each call:
    1. Verifies the essay belongs to *teacher_id* (tenant isolation).
    2. Loads the latest essay version.
    3. Strips HTML tags → derives plain-text ``content`` for the LLM pipeline.
    4. Appends a snapshot record (seq, ts, word_count, html_content) to the
       version's ``writing_snapshots`` JSONB array.
    5. Updates ``EssayVersion.content`` and ``word_count``.
    6. Commits.

    The function is idempotent to duplicate payloads — identical content sent
    twice simply adds a second snapshot entry (no deduplication is performed
    at this layer; the timeline consumer in M5-10 is responsible for
    coalescing identical snapshots).

    Args:
        db: Async database session.
        teacher_id: The authenticated teacher's UUID (tenant scoping).
        essay_id: Target essay UUID.
        html_content: Raw innerHTML string from the browser editor (sanitized
            server-side before persisting).
        word_count: Pre-computed word count (HTML tags stripped, split on whitespace).

    Returns:
        A :class:`~app.schemas.essay.WriteSnapshotResponse`.

    Raises:
        NotFoundError:   Essay or its latest version is not found.
        ForbiddenError:  Essay belongs to a different teacher.
        ValidationError: Essay was created via file upload (``writing_snapshots``
            is ``NULL``); only browser-composed essays accept snapshots.

    No student PII appears in any log output.
    """
    # Load the latest essay version with teacher ownership enforced in the
    # same JOIN query (Essay → Assignment → Class.teacher_id).  The FOR UPDATE
    # lock prevents concurrent snapshot writes from computing the same seq
    # number and losing data.
    version_result = await db.execute(
        select(EssayVersion)
        .join(Essay, EssayVersion.essay_id == Essay.id)
        .join(Assignment, Essay.assignment_id == Assignment.id)
        .join(Class, Assignment.class_id == Class.id)
        .where(
            EssayVersion.essay_id == essay_id,
            Class.teacher_id == teacher_id,
        )
        .order_by(EssayVersion.version_number.desc())
        .limit(1)
        .with_for_update(of=EssayVersion)
    )
    version = version_result.scalar_one_or_none()
    if version is None:
        # Distinguish 403 (cross-teacher) from 404 (no version) by calling
        # the ownership helper, which raises the appropriate domain error.
        await _get_essay_for_teacher(db, essay_id, teacher_id)
        raise NotFoundError("Essay version not found.")

    # Reject snapshot saves against file-upload essays.  writing_snapshots is
    # NULL for essays ingested via file upload; only browser-composed essays
    # (created by POST .../essays/compose) have an initialised [] array.
    if version.writing_snapshots is None:
        raise ValidationError(
            "Writing snapshots are not supported for file-upload essays.",
            field="essay_id",
        )

    # Sanitize the HTML before persisting to prevent stored XSS.
    safe_html = _sanitize_html_content(html_content)

    # Derive plain-text content from the sanitized HTML (for LLM grading
    # compatibility) and compute word count server-side.  The client-supplied
    # word_count is accepted in the request body for schema compatibility but
    # is ignored for storage — using the server-derived value prevents
    # inconsistent or forged counts from reaching the database.
    plain_text = _strip_html_tags(safe_html)
    server_word_count = len(plain_text.split()) if plain_text.strip() else 0

    # Build the new snapshot entry.
    existing: list[dict[str, Any]] = list(version.writing_snapshots)
    seq = len(existing) + 1
    ts = datetime.now(UTC).isoformat()
    snapshot = {
        "seq": seq,
        "ts": ts,
        "word_count": server_word_count,
        "html_content": safe_html,
    }
    existing.append(snapshot)

    # Update the version in-place.  The JSONB column requires a full
    # replacement (SQLAlchemy does not track list mutations automatically).
    version.writing_snapshots = existing
    version.content = plain_text
    version.word_count = server_word_count

    # Update the version's submitted_at so the essay list reflects recency.
    version.submitted_at = datetime.now(UTC)

    await db.commit()
    await db.refresh(version)

    logger.info(
        "Writing snapshot saved",
        extra={
            "essay_id": str(essay_id),
            "essay_version_id": str(version.id),
            "snapshot_seq": seq,
        },
    )

    return WriteSnapshotResponse(
        essay_id=essay_id,
        essay_version_id=version.id,
        snapshot_count=seq,
        word_count=server_word_count,
        saved_at=datetime.now(UTC),
    )


async def get_writing_snapshots(
    db: AsyncSession,
    teacher_id: uuid.UUID,
    essay_id: uuid.UUID,
) -> GetSnapshotsResponse:
    """Return current content and snapshot metadata for a browser-composed essay.

    Used by the browser writing interface to recover editor state after a
    page refresh or navigation.

    The response includes the current ``html_content`` (from the latest
    snapshot) and lightweight snapshot metadata (seq, ts, word_count) for
    the full history.  The individual ``html_content`` values of earlier
    snapshots are not returned here to keep the response size manageable;
    they will be used by the writing-process timeline (M5-10, M5-11).

    Args:
        db: Async database session.
        teacher_id: The authenticated teacher's UUID (tenant scoping).
        essay_id: Target essay UUID.

    Returns:
        A :class:`~app.schemas.essay.GetSnapshotsResponse`.

    Raises:
        NotFoundError:  Essay or its latest version is not found.
        ForbiddenError: Essay belongs to a different teacher.

    No student PII appears in any log output.
    """
    # Load the latest essay version with tenant isolation enforced in the
    # JOIN (Essay → Assignment → Class.teacher_id — avoids the check-then-fetch
    # two-query pattern).
    version_result = await db.execute(
        select(EssayVersion)
        .join(Essay, EssayVersion.essay_id == Essay.id)
        .join(Assignment, Essay.assignment_id == Assignment.id)
        .join(Class, Assignment.class_id == Class.id)
        .where(
            EssayVersion.essay_id == essay_id,
            Class.teacher_id == teacher_id,
        )
        .order_by(EssayVersion.version_number.desc())
        .limit(1)
    )
    version = version_result.scalar_one_or_none()
    if version is None:
        # Distinguish 403 (cross-teacher) from 404 (no version) by calling
        # the ownership helper, which raises the appropriate domain error.
        await _get_essay_for_teacher(db, essay_id, teacher_id)
        raise NotFoundError("Essay version not found.")

    # Reject file-upload essays (writing_snapshots IS NULL) — they have no
    # snapshot-backed editor state to recover.  Consistent with save_writing_snapshot()
    # which also rejects NULL essays with ValidationError.
    if version.writing_snapshots is None:
        raise ValidationError(
            "This essay was created via file upload and has no writing snapshots."
        )

    raw_snapshots: list[dict[str, Any]] = list(version.writing_snapshots)

    # Recover the latest HTML content from the most recent snapshot for
    # editor restoration.  Falls back to empty string for newly created essays.
    latest_html = raw_snapshots[-1]["html_content"] if raw_snapshots else ""

    snapshot_items = [
        SnapshotItem(
            seq=s["seq"],
            ts=s["ts"],
            word_count=s["word_count"],
        )
        for s in raw_snapshots
    ]

    return GetSnapshotsResponse(
        essay_id=essay_id,
        essay_version_id=version.id,
        current_content=latest_html,
        word_count=version.word_count,
        snapshots=snapshot_items,
    )


# ---------------------------------------------------------------------------
# Composition timeline / process signals — M5-10
# ---------------------------------------------------------------------------


async def get_process_signals(
    db: AsyncSession,
    teacher_id: uuid.UUID,
    essay_id: uuid.UUID,
) -> ProcessSignalsResponse:
    """Return composition timeline signals for a browser-composed essay.

    Signals are computed lazily on first request and cached in
    ``EssayVersion.process_signals``.  If the version's ``writing_snapshots``
    column has changed since the last computation (detected by comparing
    snapshot counts), the signals are re-computed and the cached value is
    updated.

    For file-upload essays (``writing_snapshots IS NULL``) the response has
    ``has_process_data=False`` and all list fields are empty.  This is not an
    error — the caller can surface a plain-language explanation to the teacher.

    Args:
        db: Async database session.
        teacher_id: The authenticated teacher's UUID (tenant scoping).
        essay_id: Target essay UUID.

    Returns:
        A :class:`~app.schemas.essay.ProcessSignalsResponse`.

    Raises:
        NotFoundError:  Essay or its latest version is not found.
        ForbiddenError: Essay belongs to a different teacher.

    No student PII appears in any log output.
    """
    version_result = await db.execute(
        select(EssayVersion)
        .join(Essay, EssayVersion.essay_id == Essay.id)
        .join(Assignment, Essay.assignment_id == Assignment.id)
        .join(Class, Assignment.class_id == Class.id)
        .where(
            EssayVersion.essay_id == essay_id,
            Class.teacher_id == teacher_id,
        )
        .order_by(EssayVersion.version_number.desc())
        .limit(1)
    )
    version = version_result.scalar_one_or_none()
    if version is None:
        await _get_essay_for_teacher(db, essay_id, teacher_id)
        raise NotFoundError("Essay version not found.")

    raw_snapshots: list[dict[str, Any]] = (
        version.writing_snapshots if version.writing_snapshots is not None else []
    )

    # Determine whether the cached signals are still valid.  We compare the
    # snapshot count stored in the cache with the current length of
    # writing_snapshots.  A mismatch means new snapshots were added and the
    # cache must be invalidated.
    cached: dict[str, Any] | None = version.process_signals
    cached_snapshot_count: int = int(cached.get("snapshot_count", -1)) if cached else -1
    current_snapshot_count = len(raw_snapshots)

    needs_compute = (
        cached is None
        or cached_snapshot_count != current_snapshot_count
    )

    if needs_compute:
        computed_at = datetime.now(UTC)
        timeline = analyze_writing_process(raw_snapshots)

        # Serialise the timeline to a plain dict for JSONB storage.
        payload: dict[str, Any] = {
            "snapshot_count": current_snapshot_count,
            "computed_at": computed_at.isoformat(),
            "has_process_data": timeline.has_process_data,
            "session_count": timeline.session_count,
            "active_writing_seconds": timeline.active_writing_seconds,
            "total_elapsed_seconds": timeline.total_elapsed_seconds,
            "inter_session_gaps_seconds": timeline.inter_session_gaps_seconds,
            "sessions": [
                {
                    "session_index": s.session_index,
                    "started_at": s.started_at.isoformat(),
                    "ended_at": s.ended_at.isoformat(),
                    "duration_seconds": s.duration_seconds,
                    "snapshot_count": s.snapshot_count,
                    "word_count_start": s.word_count_start,
                    "word_count_end": s.word_count_end,
                    "words_added": s.words_added,
                }
                for s in timeline.sessions
            ],
            "paste_events": [
                {
                    "snapshot_seq": e.snapshot_seq,
                    "occurred_at": e.occurred_at.isoformat(),
                    "words_before": e.words_before,
                    "words_after": e.words_after,
                    "words_added": e.words_added,
                    "session_index": e.session_index,
                }
                for e in timeline.paste_events
            ],
            "rapid_completion_events": [
                {
                    "session_index": e.session_index,
                    "duration_seconds": e.duration_seconds,
                    "words_at_start": e.words_at_start,
                    "words_at_end": e.words_at_end,
                    "completion_fraction": e.completion_fraction,
                }
                for e in timeline.rapid_completion_events
            ],
        }

        version.process_signals = payload
        await db.commit()
        await db.refresh(version)

        logger.info(
            "Process signals computed and cached",
            extra={
                "essay_id": str(essay_id),
                "essay_version_id": str(version.id),
                "session_count": timeline.session_count,
            },
        )
        cached = payload

    # Build the response from the cached (or freshly computed) payload.
    # At this point `cached` is guaranteed non-None: either it was already set
    # before the branch, or `needs_compute` ran and set `cached = payload`.
    assert cached is not None  # narrowing for mypy
    computed_at_str: str = cached["computed_at"]
    computed_at_dt = datetime.fromisoformat(computed_at_str)

    return ProcessSignalsResponse(
        essay_id=essay_id,
        essay_version_id=version.id,
        has_process_data=cached["has_process_data"],
        session_count=cached["session_count"],
        sessions=[
            SessionSegmentResponse(
                session_index=s["session_index"],
                started_at=datetime.fromisoformat(s["started_at"]),
                ended_at=datetime.fromisoformat(s["ended_at"]),
                duration_seconds=s["duration_seconds"],
                snapshot_count=s["snapshot_count"],
                word_count_start=s["word_count_start"],
                word_count_end=s["word_count_end"],
                words_added=s["words_added"],
            )
            for s in cached["sessions"]
        ],
        inter_session_gaps_seconds=cached["inter_session_gaps_seconds"],
        active_writing_seconds=cached["active_writing_seconds"],
        total_elapsed_seconds=cached["total_elapsed_seconds"],
        paste_events=[
            PasteEventResponse(
                snapshot_seq=e["snapshot_seq"],
                occurred_at=datetime.fromisoformat(e["occurred_at"]),
                words_before=e["words_before"],
                words_after=e["words_after"],
                words_added=e["words_added"],
                session_index=e["session_index"],
            )
            for e in cached["paste_events"]
        ],
        rapid_completion_events=[
            RapidCompletionEventResponse(
                session_index=e["session_index"],
                duration_seconds=e["duration_seconds"],
                words_at_start=e["words_at_start"],
                words_at_end=e["words_at_end"],
                completion_fraction=e["completion_fraction"],
            )
            for e in cached["rapid_completion_events"]
        ],
        computed_at=computed_at_dt,
    )
