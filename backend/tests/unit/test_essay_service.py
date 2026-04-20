"""Unit tests for app/services/essay.py.

Tests cover:
- validate_file_size: within limit, exactly at limit, over limit
- validate_mime_type: allowed types, disallowed type
- extract_text: dispatch to PDF / DOCX / TXT extractors; disallowed type
- normalize_text: whitespace stripping, Unicode NFC, non-printable chars,
  blank-line collapsing
- count_words: basic counting
- _sanitize_filename: path traversal stripping, unsafe char replacement, length cap
- ingest_essay: happy path (TXT, mocked DB + S3), cross-teacher 403, 404,
  student ownership/enrollment validation, s3-before-extraction ordering

No real PostgreSQL, S3, or file I/O.  All external calls are mocked.
No student PII in fixtures.
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.exceptions import FileTooLargeError, FileTypeNotAllowedError, ForbiddenError, NotFoundError
from app.services.essay import (
    _sanitize_filename,
    count_words,
    extract_text,
    normalize_text,
    validate_file_size,
    validate_mime_type,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_assignment(
    assignment_id: uuid.UUID | None = None,
    teacher_id: uuid.UUID | None = None,
) -> MagicMock:
    a = MagicMock()
    a.id = assignment_id or uuid.uuid4()
    a.teacher_id = teacher_id or uuid.uuid4()
    return a


def _make_essay(
    essay_id: uuid.UUID | None = None,
    assignment_id: uuid.UUID | None = None,
    student_id: uuid.UUID | None = None,
) -> MagicMock:
    e = MagicMock()
    e.id = essay_id or uuid.uuid4()
    e.assignment_id = assignment_id or uuid.uuid4()
    e.student_id = student_id
    return e


def _make_version(
    version_id: uuid.UUID | None = None,
    essay_id: uuid.UUID | None = None,
    word_count: int = 100,
    file_storage_key: str = "essays/a/b/test.txt",
) -> MagicMock:
    v = MagicMock()
    v.id = version_id or uuid.uuid4()
    v.essay_id = essay_id or uuid.uuid4()
    v.word_count = word_count
    v.file_storage_key = file_storage_key
    return v


# ---------------------------------------------------------------------------
# validate_file_size
# ---------------------------------------------------------------------------


class TestValidateFileSize:
    def test_within_limit_passes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("app.services.essay.settings.max_essay_file_size_mb", 10)
        data = b"x" * (9 * 1024 * 1024)
        validate_file_size(data)  # should not raise

    def test_at_limit_passes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("app.services.essay.settings.max_essay_file_size_mb", 10)
        data = b"x" * (10 * 1024 * 1024)
        validate_file_size(data)  # exactly at limit — should not raise

    def test_over_limit_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("app.services.essay.settings.max_essay_file_size_mb", 1)
        data = b"x" * (1 * 1024 * 1024 + 1)
        with pytest.raises(FileTooLargeError):
            validate_file_size(data)


# ---------------------------------------------------------------------------
# validate_mime_type
# ---------------------------------------------------------------------------


class TestValidateMimeType:
    @pytest.mark.parametrize(
        "mime",
        [
            "application/pdf",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "text/plain",
        ],
    )
    def test_allowed_type_returns_mime(self, mime: str) -> None:
        with patch("app.services.essay._detect_mime_type", return_value=mime):
            result = validate_mime_type(b"data")
        assert result == mime, f"Expected {mime!r}, got {result!r}"

    def test_disallowed_type_raises(self) -> None:
        with (
            patch("app.services.essay._detect_mime_type", return_value="image/jpeg"),
            pytest.raises(FileTypeNotAllowedError),
        ):
            validate_mime_type(b"data")

    def test_disallowed_type_error_includes_field(self) -> None:
        with patch("app.services.essay._detect_mime_type", return_value="application/zip"):
            try:
                validate_mime_type(b"data")
            except FileTypeNotAllowedError as exc:
                assert exc.field == "file", f"Expected field='file', got {exc.field!r}"
            else:
                pytest.fail("FileTypeNotAllowedError not raised")


# ---------------------------------------------------------------------------
# extract_text — dispatch
# ---------------------------------------------------------------------------


class TestExtractText:
    def test_pdf_dispatches_to_pdf_extractor(self) -> None:
        with patch("app.services.essay._extract_text_pdf", return_value="pdf text") as mock_pdf:
            result = extract_text(b"pdf bytes", "application/pdf")
        mock_pdf.assert_called_once_with(b"pdf bytes")
        assert result == "pdf text"

    def test_docx_dispatches_to_docx_extractor(self) -> None:
        mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        with patch("app.services.essay._extract_text_docx", return_value="docx text") as mock_docx:
            result = extract_text(b"docx bytes", mime)
        mock_docx.assert_called_once_with(b"docx bytes")
        assert result == "docx text"

    def test_txt_dispatches_to_txt_extractor(self) -> None:
        with patch("app.services.essay._extract_text_txt", return_value="plain text") as mock_txt:
            result = extract_text(b"plain bytes", "text/plain")
        mock_txt.assert_called_once_with(b"plain bytes")
        assert result == "plain text"

    def test_unknown_mime_raises(self) -> None:
        with pytest.raises(FileTypeNotAllowedError):
            extract_text(b"data", "application/zip")


# ---------------------------------------------------------------------------
# normalize_text
# ---------------------------------------------------------------------------


class TestNormalizeText:
    def test_strips_leading_trailing_whitespace(self) -> None:
        result = normalize_text("  hello world  ")
        assert result == "hello world"

    def test_strips_trailing_whitespace_per_line(self) -> None:
        result = normalize_text("line one   \nline two   ")
        assert result == "line one\nline two"

    def test_nfc_normalization(self) -> None:
        # café composed vs decomposed
        decomposed = "cafe\u0301"  # e + combining acute accent
        composed = "caf\u00e9"  # é precomposed
        result = normalize_text(decomposed)
        assert result == composed, f"Expected NFC form, got {result!r}"

    def test_removes_non_printable_chars(self) -> None:
        text = "hello\x00world\x01"
        result = normalize_text(text)
        assert "\x00" not in result
        assert "\x01" not in result
        assert "hello" in result
        assert "world" in result

    def test_preserves_newlines(self) -> None:
        text = "line one\nline two\nline three"
        result = normalize_text(text)
        assert result.count("\n") == 2

    def test_collapses_excessive_blank_lines(self) -> None:
        text = "para one\n\n\n\n\npara two"
        result = normalize_text(text)
        assert "\n\n\n" not in result
        assert "para one" in result
        assert "para two" in result

    def test_empty_string_returns_empty(self) -> None:
        assert normalize_text("") == ""


# ---------------------------------------------------------------------------
# count_words
# ---------------------------------------------------------------------------


class TestCountWords:
    def test_basic_sentence(self) -> None:
        assert count_words("The quick brown fox jumps") == 5

    def test_empty_string(self) -> None:
        assert count_words("") == 0

    def test_extra_whitespace(self) -> None:
        assert count_words("  hello   world  ") == 2

    def test_multiline(self) -> None:
        assert count_words("line one\nline two") == 4


# ---------------------------------------------------------------------------
# _sanitize_filename
# ---------------------------------------------------------------------------


class TestSanitizeFilename:
    def test_strips_directory_separators(self) -> None:
        result = _sanitize_filename("../../etc/passwd")
        assert "/" not in result
        assert "\\" not in result

    def test_keeps_safe_chars(self) -> None:
        result = _sanitize_filename("my-essay_v2.txt")
        assert result == "my-essay_v2.txt"

    def test_replaces_unsafe_chars(self) -> None:
        result = _sanitize_filename("essay with spaces!.pdf")
        assert " " not in result
        assert "!" not in result

    def test_truncates_long_name(self) -> None:
        long_name = "a" * 300 + ".txt"
        result = _sanitize_filename(long_name)
        assert len(result) <= 200

    def test_empty_after_sanitization_returns_uuid_fallback(self) -> None:
        # A bare "/" has an empty basename, so sanitization yields "" → fallback.
        result = _sanitize_filename("/")
        assert len(result) > 0
        assert result.startswith("essay_")


# ---------------------------------------------------------------------------
# ingest_essay — happy path (TXT, everything mocked)
# ---------------------------------------------------------------------------


class TestIngestEssay:
    """Integration-style unit tests for ingest_essay with all I/O mocked."""

    def _make_db(self) -> MagicMock:
        """Return a minimal AsyncSession mock."""
        db = MagicMock()
        db.execute = AsyncMock()
        db.flush = AsyncMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock()
        db.add = MagicMock()
        return db

    def _setup_ownership_query(
        self,
        db: MagicMock,
        assignment_id: uuid.UUID,
        teacher_id: uuid.UUID,
    ) -> None:
        """Make db.execute return an ownership row for the first two queries."""
        ownership_row = MagicMock()
        ownership_row.teacher_id = teacher_id

        assignment_mock = _make_assignment(assignment_id, teacher_id)

        first_result = MagicMock()
        first_result.one_or_none = MagicMock(return_value=ownership_row)

        second_result = MagicMock()
        second_result.scalar_one_or_none = MagicMock(return_value=assignment_mock)

        db.execute = AsyncMock(side_effect=[first_result, second_result])

    @pytest.mark.asyncio
    async def test_happy_path_txt(self) -> None:
        from app.services.essay import ingest_essay

        teacher_id = uuid.uuid4()
        assignment_id = uuid.uuid4()
        data = b"This is a test essay with enough words to be valid content."

        db = self._make_db()
        self._setup_ownership_query(db, assignment_id, teacher_id)

        # After flush, essay.id must be set; simulate by making db.add capture the essay
        essay_ids: list[Any] = []

        def _capture_add(obj: Any) -> None:
            if hasattr(obj, "assignment_id"):
                obj.id = uuid.uuid4()
                essay_ids.append(obj)

        db.add.side_effect = _capture_add

        with (
            patch("app.services.essay.validate_mime_type", return_value="text/plain"),
            patch("app.services.essay.upload_file") as mock_upload,
            patch(
                "app.services.essay.extract_text", return_value="This is a test essay"
            ) as mock_extract,
        ):
            essay, version = await ingest_essay(
                db=db,
                teacher_id=teacher_id,
                assignment_id=assignment_id,
                filename="essay.txt",
                data=data,
            )

        mock_upload.assert_called_once()
        mock_extract.assert_called_once_with(data, "text/plain")
        db.commit.assert_called_once()

        assert essay is not None, "Expected essay to be created"
        assert version is not None, "Expected essay version to be created"

    @pytest.mark.asyncio
    async def test_s3_upload_called_before_extraction(self) -> None:
        """S3 upload must happen before text extraction."""
        from app.services.essay import ingest_essay

        teacher_id = uuid.uuid4()
        assignment_id = uuid.uuid4()

        db = self._make_db()
        self._setup_ownership_query(db, assignment_id, teacher_id)

        call_order: list[str] = []

        def _mock_upload(*args: Any, **kwargs: Any) -> None:
            call_order.append("upload")

        def _mock_extract(*args: Any, **kwargs: Any) -> str:
            call_order.append("extract")
            return "extracted text content here for testing"

        with (
            patch("app.services.essay.validate_mime_type", return_value="text/plain"),
            patch("app.services.essay.upload_file", side_effect=_mock_upload),
            patch("app.services.essay.extract_text", side_effect=_mock_extract),
        ):
            await ingest_essay(
                db=db,
                teacher_id=teacher_id,
                assignment_id=assignment_id,
                filename="essay.txt",
                data=b"content",
            )

        assert call_order == ["upload", "extract"], (
            f"Expected upload before extract, got order: {call_order}"
        )

    @pytest.mark.asyncio
    async def test_not_found_assignment(self) -> None:
        from app.services.essay import ingest_essay

        db = self._make_db()
        not_found_result = MagicMock()
        not_found_result.one_or_none = MagicMock(return_value=None)
        db.execute = AsyncMock(return_value=not_found_result)

        with (
            patch("app.services.essay.validate_mime_type", return_value="text/plain"),
            pytest.raises(NotFoundError),
        ):
            await ingest_essay(
                db=db,
                teacher_id=uuid.uuid4(),
                assignment_id=uuid.uuid4(),
                filename="essay.txt",
                data=b"content",
            )

    @pytest.mark.asyncio
    async def test_cross_teacher_raises_forbidden(self) -> None:
        from app.services.essay import ingest_essay

        teacher_id = uuid.uuid4()
        other_teacher_id = uuid.uuid4()

        db = self._make_db()
        ownership_row = MagicMock()
        ownership_row.teacher_id = other_teacher_id  # different teacher

        first_result = MagicMock()
        first_result.one_or_none = MagicMock(return_value=ownership_row)
        db.execute = AsyncMock(return_value=first_result)

        with (
            patch("app.services.essay.validate_mime_type", return_value="text/plain"),
            pytest.raises(ForbiddenError),
        ):
            await ingest_essay(
                db=db,
                teacher_id=teacher_id,
                assignment_id=uuid.uuid4(),
                filename="essay.txt",
                data=b"content",
            )

    @pytest.mark.asyncio
    async def test_file_too_large_raises_before_db(self) -> None:
        from app.services.essay import ingest_essay

        db = self._make_db()

        with (
            patch("app.services.essay.settings.max_essay_file_size_mb", 1),
            pytest.raises(FileTooLargeError),
        ):
            await ingest_essay(
                db=db,
                teacher_id=uuid.uuid4(),
                assignment_id=uuid.uuid4(),
                filename="big.txt",
                data=b"x" * (1 * 1024 * 1024 + 1),
            )

        # DB should not have been touched
        db.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_student_not_owned_by_teacher_raises_not_found(self) -> None:
        from app.services.essay import ingest_essay

        teacher_id = uuid.uuid4()
        assignment_id = uuid.uuid4()
        student_id = uuid.uuid4()

        db = self._make_db()
        self._setup_ownership_query(db, assignment_id, teacher_id)

        # Student lookup (3rd execute) returns None — student not found for teacher.
        student_result = MagicMock()
        student_result.scalar_one_or_none = MagicMock(return_value=None)
        # Append to existing side_effect list
        existing_side_effect = list(db.execute.side_effect)
        db.execute = AsyncMock(side_effect=[*existing_side_effect, student_result])

        with (
            patch("app.services.essay.validate_mime_type", return_value="text/plain"),
            pytest.raises(NotFoundError),
        ):
            await ingest_essay(
                db=db,
                teacher_id=teacher_id,
                assignment_id=assignment_id,
                filename="essay.txt",
                data=b"content",
                student_id=student_id,
            )

    @pytest.mark.asyncio
    async def test_student_not_enrolled_raises_forbidden(self) -> None:
        from app.services.essay import ingest_essay

        teacher_id = uuid.uuid4()
        assignment_id = uuid.uuid4()
        student_id = uuid.uuid4()

        db = self._make_db()
        self._setup_ownership_query(db, assignment_id, teacher_id)

        # Student ownership check passes (4th execute).
        student_result = MagicMock()
        student_result.scalar_one_or_none = MagicMock(return_value=student_id)

        # Enrollment check returns None — student not enrolled.
        enrollment_result = MagicMock()
        enrollment_result.scalar_one_or_none = MagicMock(return_value=None)

        existing_side_effect = list(db.execute.side_effect)
        db.execute = AsyncMock(
            side_effect=[*existing_side_effect, student_result, enrollment_result]
        )

        with (
            patch("app.services.essay.validate_mime_type", return_value="text/plain"),
            pytest.raises(ForbiddenError),
        ):
            await ingest_essay(
                db=db,
                teacher_id=teacher_id,
                assignment_id=assignment_id,
                filename="essay.txt",
                data=b"content",
                student_id=student_id,
            )

    @pytest.mark.asyncio
    async def test_extraction_failure_triggers_s3_cleanup(self) -> None:
        """When text extraction raises, delete_file must be called with the S3 key."""
        from app.services.essay import ingest_essay

        teacher_id = uuid.uuid4()
        assignment_id = uuid.uuid4()

        db = self._make_db()
        self._setup_ownership_query(db, assignment_id, teacher_id)

        def _capture_add(obj: Any) -> None:
            if hasattr(obj, "assignment_id"):
                obj.id = uuid.uuid4()

        db.add.side_effect = _capture_add

        with (
            patch("app.services.essay.validate_mime_type", return_value="text/plain"),
            patch("app.services.essay.upload_file"),
            patch(
                "app.services.essay.extract_text",
                side_effect=RuntimeError("extraction failed"),
            ),
            patch("app.services.essay.delete_file") as mock_delete,
            pytest.raises(RuntimeError, match="extraction failed"),
        ):
            await ingest_essay(
                db=db,
                teacher_id=teacher_id,
                assignment_id=assignment_id,
                filename="essay.txt",
                data=b"content",
            )

        mock_delete.assert_called_once()
        called_key = mock_delete.call_args[0][0]
        assert called_key.startswith(f"essays/{assignment_id}/"), (
            f"delete_file called with unexpected key: {called_key!r}"
        )
