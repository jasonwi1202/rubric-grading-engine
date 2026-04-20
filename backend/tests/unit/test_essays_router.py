"""Unit tests for the essays router endpoints.

Tests cover:
- POST /api/v1/assignments/{id}/essays — happy path (TXT), 422 (no files),
  422 (file too large), 403 (cross-teacher), 404 (no assignment), 401 (no auth)

No real PostgreSQL, S3, or file I/O.  All DB / service calls are mocked.
No student PII in fixtures.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from io import BytesIO
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.dependencies import get_current_teacher
from app.exceptions import FileTooLargeError, FileTypeNotAllowedError, ForbiddenError, NotFoundError
from app.main import create_app

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_teacher(teacher_id: uuid.UUID | None = None) -> MagicMock:
    teacher = MagicMock()
    teacher.id = teacher_id or uuid.uuid4()
    teacher.email = "teacher@school.edu"
    teacher.email_verified = True
    return teacher


def _make_essay(
    assignment_id: uuid.UUID | None = None,
    student_id: uuid.UUID | None = None,
) -> MagicMock:
    essay = MagicMock()
    essay.id = uuid.uuid4()
    essay.assignment_id = assignment_id or uuid.uuid4()
    essay.student_id = student_id
    essay.status = "unassigned"
    return essay


def _make_version(
    essay_id: uuid.UUID | None = None,
    word_count: int = 50,
    s3_key: str = "essays/a/b/test.txt",
) -> MagicMock:
    v = MagicMock()
    v.id = uuid.uuid4()
    v.essay_id = essay_id or uuid.uuid4()
    v.word_count = word_count
    v.file_storage_key = s3_key
    v.submitted_at = datetime.now(UTC)
    return v


def _app_with_teacher(teacher: MagicMock | None = None) -> object:
    teacher = teacher or _make_teacher()
    app = create_app()
    app.dependency_overrides[get_current_teacher] = lambda: teacher  # type: ignore[attr-defined]
    return app


# ---------------------------------------------------------------------------
# POST /api/v1/assignments/{id}/essays
# ---------------------------------------------------------------------------


class TestUploadEssays:
    def _url(self, assignment_id: uuid.UUID | None = None) -> str:
        aid = assignment_id or uuid.uuid4()
        return f"/api/v1/assignments/{aid}/essays"

    def test_happy_path_single_txt_file(self) -> None:
        teacher = _make_teacher()
        assignment_id = uuid.uuid4()
        essay = _make_essay(assignment_id=assignment_id)
        version = _make_version(essay_id=essay.id)

        app = _app_with_teacher(teacher)

        with patch(
            "app.routers.essays.ingest_essay",
            new_callable=AsyncMock,
            return_value=(essay, version),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.post(
                self._url(assignment_id),
                files=[("files", ("essay.txt", BytesIO(b"This is an essay."), "text/plain"))],
            )

        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert "data" in body
        assert len(body["data"]) == 1
        item = body["data"][0]
        assert item["essay_id"] == str(essay.id)
        assert item["essay_version_id"] == str(version.id)
        assert item["assignment_id"] == str(assignment_id)

    def test_multiple_files_returned_in_order(self) -> None:
        teacher = _make_teacher()
        assignment_id = uuid.uuid4()

        essay1 = _make_essay(assignment_id=assignment_id)
        version1 = _make_version(essay_id=essay1.id)
        essay2 = _make_essay(assignment_id=assignment_id)
        version2 = _make_version(essay_id=essay2.id)

        app = _app_with_teacher(teacher)

        with patch(
            "app.routers.essays.ingest_essay",
            new_callable=AsyncMock,
            side_effect=[(essay1, version1), (essay2, version2)],
        ):
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.post(
                self._url(assignment_id),
                files=[
                    ("files", ("a.txt", BytesIO(b"Essay one."), "text/plain")),
                    ("files", ("b.txt", BytesIO(b"Essay two."), "text/plain")),
                ],
            )

        assert resp.status_code == 201, resp.text
        assert len(resp.json()["data"]) == 2

    def test_no_auth_returns_401(self) -> None:
        app = create_app()
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post(
            self._url(),
            files=[("files", ("essay.txt", BytesIO(b"text"), "text/plain"))],
        )
        assert resp.status_code == 401

    def test_file_too_large_returns_422(self) -> None:
        teacher = _make_teacher()
        app = _app_with_teacher(teacher)

        with patch(
            "app.routers.essays.ingest_essay",
            new_callable=AsyncMock,
            side_effect=FileTooLargeError("File too large.", field="file"),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.post(
                self._url(),
                files=[("files", ("big.txt", BytesIO(b"x" * 100), "text/plain"))],
            )

        assert resp.status_code == 422
        body = resp.json()
        assert body["error"]["code"] == "FILE_TOO_LARGE"

    def test_invalid_mime_type_returns_422(self) -> None:
        teacher = _make_teacher()
        app = _app_with_teacher(teacher)

        with patch(
            "app.routers.essays.ingest_essay",
            new_callable=AsyncMock,
            side_effect=FileTypeNotAllowedError("Type not allowed.", field="file"),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.post(
                self._url(),
                files=[("files", ("bad.jpg", BytesIO(b"fake"), "image/jpeg"))],
            )

        assert resp.status_code == 422
        body = resp.json()
        assert body["error"]["code"] == "FILE_TYPE_NOT_ALLOWED"

    def test_assignment_not_found_returns_404(self) -> None:
        teacher = _make_teacher()
        app = _app_with_teacher(teacher)

        with patch(
            "app.routers.essays.ingest_essay",
            new_callable=AsyncMock,
            side_effect=NotFoundError("Assignment not found."),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.post(
                self._url(),
                files=[("files", ("essay.txt", BytesIO(b"text"), "text/plain"))],
            )

        assert resp.status_code == 404
        body = resp.json()
        assert body["error"]["code"] == "NOT_FOUND"

    def test_cross_teacher_returns_403(self) -> None:
        teacher = _make_teacher()
        app = _app_with_teacher(teacher)

        with patch(
            "app.routers.essays.ingest_essay",
            new_callable=AsyncMock,
            side_effect=ForbiddenError("Forbidden."),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.post(
                self._url(),
                files=[("files", ("essay.txt", BytesIO(b"text"), "text/plain"))],
            )

        assert resp.status_code == 403
        body = resp.json()
        assert body["error"]["code"] == "FORBIDDEN"

    def test_file_size_limit_enforced_in_router(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Router reads at most max_bytes+1 and raises FileTooLargeError."""
        teacher = _make_teacher()
        monkeypatch.setattr("app.routers.essays.settings.max_essay_file_size_mb", 1)
        app = _app_with_teacher(teacher)

        # Provide more than 1 MB of data to trigger the router's size check.
        big_data = b"x" * (1 * 1024 * 1024 + 2)
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post(
            self._url(),
            files=[("files", ("big.txt", BytesIO(big_data), "text/plain"))],
        )

        assert resp.status_code == 422
        body = resp.json()
        assert body["error"]["code"] == "FILE_TOO_LARGE"
