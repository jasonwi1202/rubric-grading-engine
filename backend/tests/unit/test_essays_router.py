"""Unit tests for the essays router endpoints.

Tests cover:
- POST /api/v1/assignments/{id}/essays — happy path (TXT), 422 (no files),
  422 (file too large), 403 (cross-teacher), 404 (no assignment), 401 (no auth)
- GET  /api/v1/assignments/{id}/essays — happy path, 401, 404, 403
- PATCH /api/v1/essays/{id}            — happy path, 401, 404, 403, 422

No real PostgreSQL, S3, or file I/O.  All DB / service calls are mocked.
No student PII in fixtures.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from io import BytesIO
from typing import Literal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.dependencies import get_current_teacher
from app.exceptions import FileTooLargeError, FileTypeNotAllowedError, ForbiddenError, NotFoundError
from app.main import create_app
from app.schemas.essay import EssayListItemResponse, ResubmitEssayResponse
from app.services.student_matching import AutoAssignResult

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


def _make_auto_result(
    status: Literal["assigned", "ambiguous", "unassigned"] = "unassigned",
) -> AutoAssignResult:
    return AutoAssignResult(status=status, student_id=None, match_count=0)


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

        with (
            patch(
                "app.routers.essays.ingest_essay",
                new_callable=AsyncMock,
                return_value=(essay, version, _make_auto_result()),
            ),
            patch("app.routers.essays._compute_embedding_task") as mock_task,
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
        mock_task.delay.assert_called_once_with(
            str(version.id), str(essay.assignment_id), str(teacher.id)
        )

    def test_multiple_files_returned_in_order(self) -> None:
        teacher = _make_teacher()
        assignment_id = uuid.uuid4()

        essay1 = _make_essay(assignment_id=assignment_id)
        version1 = _make_version(essay_id=essay1.id)
        essay2 = _make_essay(assignment_id=assignment_id)
        version2 = _make_version(essay_id=essay2.id)

        app = _app_with_teacher(teacher)

        with (
            patch(
                "app.routers.essays.ingest_essay",
                new_callable=AsyncMock,
                side_effect=[
                    (essay1, version1, _make_auto_result()),
                    (essay2, version2, _make_auto_result()),
                ],
            ),
            patch("app.routers.essays._compute_embedding_task"),
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

    def test_multiple_files_with_student_id_returns_422(self) -> None:
        """Uploading more than one file with a student_id is rejected."""
        teacher = _make_teacher()
        app = _app_with_teacher(teacher)
        student_id = uuid.uuid4()

        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post(
            self._url(),
            data={"student_id": str(student_id)},
            files=[
                ("files", ("a.txt", BytesIO(b"Essay one."), "text/plain")),
                ("files", ("b.txt", BytesIO(b"Essay two."), "text/plain")),
            ],
        )

        assert resp.status_code == 422, resp.text
        body = resp.json()
        assert body["error"]["code"] == "VALIDATION_ERROR"


# ---------------------------------------------------------------------------
# GET /api/v1/assignments/{id}/essays
# ---------------------------------------------------------------------------


class TestListEssays:
    def _url(self, assignment_id: uuid.UUID | None = None) -> str:
        aid = assignment_id or uuid.uuid4()
        return f"/api/v1/assignments/{aid}/essays"

    def test_happy_path_returns_essay_list(self) -> None:
        teacher = _make_teacher()
        assignment_id = uuid.uuid4()
        item = EssayListItemResponse(
            essay_id=uuid.uuid4(),
            assignment_id=assignment_id,
            student_id=None,
            student_name=None,
            status="unassigned",
            word_count=200,
            submitted_at=datetime.now(UTC),
            auto_assign_status="unassigned",
        )

        app = _app_with_teacher(teacher)

        with patch(
            "app.routers.essays.list_essays_for_assignment",
            new_callable=AsyncMock,
            return_value=[item],
        ):
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.get(self._url(assignment_id))

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert len(body["data"]) == 1
        assert body["data"][0]["auto_assign_status"] == "unassigned"
        assert body["data"][0]["student_id"] is None

    def test_no_auth_returns_401(self) -> None:
        app = create_app()
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get(self._url())
        assert resp.status_code == 401

    def test_assignment_not_found_returns_404(self) -> None:
        teacher = _make_teacher()
        app = _app_with_teacher(teacher)

        with patch(
            "app.routers.essays.list_essays_for_assignment",
            new_callable=AsyncMock,
            side_effect=NotFoundError("Assignment not found."),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.get(self._url())

        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "NOT_FOUND"

    def test_cross_teacher_returns_403(self) -> None:
        teacher = _make_teacher()
        app = _app_with_teacher(teacher)

        with patch(
            "app.routers.essays.list_essays_for_assignment",
            new_callable=AsyncMock,
            side_effect=ForbiddenError("Forbidden."),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.get(self._url())

        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "FORBIDDEN"


# ---------------------------------------------------------------------------
# PATCH /api/v1/essays/{id}
# ---------------------------------------------------------------------------


class TestAssignEssay:
    def _url(self, essay_id: uuid.UUID | None = None) -> str:
        eid = essay_id or uuid.uuid4()
        return f"/api/v1/essays/{eid}"

    def test_happy_path_assigns_student(self) -> None:
        teacher = _make_teacher()
        essay_id = uuid.uuid4()
        student_id = uuid.uuid4()
        assignment_id = uuid.uuid4()
        item = EssayListItemResponse(
            essay_id=essay_id,
            assignment_id=assignment_id,
            student_id=student_id,
            student_name=None,
            status="queued",
            word_count=200,
            submitted_at=datetime.now(UTC),
            auto_assign_status="assigned",
        )

        app = _app_with_teacher(teacher)

        with patch(
            "app.routers.essays.assign_essay_to_student",
            new_callable=AsyncMock,
            return_value=item,
        ):
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.patch(
                self._url(essay_id),
                json={"student_id": str(student_id)},
            )

        assert resp.status_code == 200, resp.text
        body = resp.json()["data"]
        assert body["auto_assign_status"] == "assigned"
        assert body["student_id"] == str(student_id)

    def test_no_auth_returns_401(self) -> None:
        app = create_app()
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.patch(
            self._url(),
            json={"student_id": str(uuid.uuid4())},
        )
        assert resp.status_code == 401

    def test_essay_not_found_returns_404(self) -> None:
        teacher = _make_teacher()
        app = _app_with_teacher(teacher)

        with patch(
            "app.routers.essays.assign_essay_to_student",
            new_callable=AsyncMock,
            side_effect=NotFoundError("Essay not found."),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.patch(
                self._url(),
                json={"student_id": str(uuid.uuid4())},
            )

        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "NOT_FOUND"

    def test_cross_teacher_returns_403(self) -> None:
        teacher = _make_teacher()
        app = _app_with_teacher(teacher)

        with patch(
            "app.routers.essays.assign_essay_to_student",
            new_callable=AsyncMock,
            side_effect=ForbiddenError("Forbidden."),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.patch(
                self._url(),
                json={"student_id": str(uuid.uuid4())},
            )

        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "FORBIDDEN"

    def test_student_not_enrolled_returns_403(self) -> None:
        teacher = _make_teacher()
        app = _app_with_teacher(teacher)

        with patch(
            "app.routers.essays.assign_essay_to_student",
            new_callable=AsyncMock,
            side_effect=ForbiddenError("Student is not enrolled in this assignment's class."),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.patch(
                self._url(),
                json={"student_id": str(uuid.uuid4())},
            )

        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "FORBIDDEN"

    def test_missing_student_id_returns_422(self) -> None:
        teacher = _make_teacher()
        app = _app_with_teacher(teacher)
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.patch(self._url(), json={})
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# POST /api/v1/essays/{id}/resubmit  (M6-10)
# ---------------------------------------------------------------------------


class TestResubmitEssay:
    def _url(self, essay_id: uuid.UUID | None = None) -> str:
        eid = essay_id or uuid.uuid4()
        return f"/api/v1/essays/{eid}/resubmit"

    def _make_resubmit_response(
        self,
        essay_id: uuid.UUID | None = None,
        assignment_id: uuid.UUID | None = None,
        version_number: int = 2,
    ) -> ResubmitEssayResponse:
        eid = essay_id or uuid.uuid4()
        return ResubmitEssayResponse(
            essay_id=eid,
            essay_version_id=uuid.uuid4(),
            version_number=version_number,
            assignment_id=assignment_id or uuid.uuid4(),
            word_count=150,
            file_storage_key="essays/a/b/v2/revised.txt",
            submitted_at=datetime.now(UTC),
        )

    def test_happy_path_returns_201(self) -> None:
        teacher = _make_teacher()
        essay_id = uuid.uuid4()
        resubmit_resp = self._make_resubmit_response(essay_id=essay_id)

        app = _app_with_teacher(teacher)

        with (
            patch(
                "app.routers.essays.resubmit_essay",
                new_callable=AsyncMock,
                return_value=resubmit_resp,
            ),
            patch("app.routers.essays._compute_embedding_task"),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.post(
                self._url(essay_id),
                files=[("file", ("revised.txt", BytesIO(b"Revised essay text."), "text/plain"))],
            )

        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert "data" in body
        data = body["data"]
        assert data["essay_id"] == str(essay_id)
        assert data["version_number"] == 2
        assert data["word_count"] == 150

    def test_no_auth_returns_401(self) -> None:
        app = create_app()
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post(
            self._url(),
            files=[("file", ("revised.txt", BytesIO(b"text"), "text/plain"))],
        )
        assert resp.status_code == 401

    def test_essay_not_found_returns_404(self) -> None:
        teacher = _make_teacher()
        app = _app_with_teacher(teacher)

        with patch(
            "app.routers.essays.resubmit_essay",
            new_callable=AsyncMock,
            side_effect=NotFoundError("Essay not found."),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.post(
                self._url(),
                files=[("file", ("revised.txt", BytesIO(b"text"), "text/plain"))],
            )

        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "NOT_FOUND"

    def test_cross_teacher_returns_404(self) -> None:
        teacher = _make_teacher()
        app = _app_with_teacher(teacher)

        with patch(
            "app.routers.essays.resubmit_essay",
            new_callable=AsyncMock,
            side_effect=NotFoundError("Essay not found."),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.post(
                self._url(),
                files=[("file", ("revised.txt", BytesIO(b"text"), "text/plain"))],
            )

        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "NOT_FOUND"

    def test_resubmission_disabled_returns_409(self) -> None:
        from app.exceptions import ResubmissionDisabledError

        teacher = _make_teacher()
        app = _app_with_teacher(teacher)

        with patch(
            "app.routers.essays.resubmit_essay",
            new_callable=AsyncMock,
            side_effect=ResubmissionDisabledError("Resubmission is not enabled."),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.post(
                self._url(),
                files=[("file", ("revised.txt", BytesIO(b"text"), "text/plain"))],
            )

        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "RESUBMISSION_DISABLED"

    def test_resubmission_limit_reached_returns_409(self) -> None:
        from app.exceptions import ResubmissionLimitReachedError

        teacher = _make_teacher()
        app = _app_with_teacher(teacher)

        with patch(
            "app.routers.essays.resubmit_essay",
            new_callable=AsyncMock,
            side_effect=ResubmissionLimitReachedError("Limit reached."),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.post(
                self._url(),
                files=[("file", ("revised.txt", BytesIO(b"text"), "text/plain"))],
            )

        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "RESUBMISSION_LIMIT_REACHED"

    def test_file_too_large_returns_422(self, monkeypatch: pytest.MonkeyPatch) -> None:
        teacher = _make_teacher()
        monkeypatch.setattr("app.routers.essays.settings.max_essay_file_size_mb", 1)
        app = _app_with_teacher(teacher)

        big_data = b"x" * (1 * 1024 * 1024 + 2)
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post(
            self._url(),
            files=[("file", ("big.txt", BytesIO(big_data), "text/plain"))],
        )

        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "FILE_TOO_LARGE"

    def test_invalid_mime_type_returns_422(self) -> None:
        teacher = _make_teacher()
        app = _app_with_teacher(teacher)

        with patch(
            "app.routers.essays.resubmit_essay",
            new_callable=AsyncMock,
            side_effect=FileTypeNotAllowedError("Type not allowed.", field="file"),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.post(
                self._url(),
                files=[("file", ("bad.jpg", BytesIO(b"fake"), "image/jpeg"))],
            )

        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "FILE_TYPE_NOT_ALLOWED"

    def test_embedding_task_failure_does_not_break_response(self) -> None:
        """A broker outage on embedding enqueue must not fail the 201 response."""
        teacher = _make_teacher()
        essay_id = uuid.uuid4()
        resubmit_resp = self._make_resubmit_response(essay_id=essay_id)

        app = _app_with_teacher(teacher)

        failing_task = MagicMock()
        failing_task.delay.side_effect = Exception("broker down")

        with (
            patch(
                "app.routers.essays.resubmit_essay",
                new_callable=AsyncMock,
                return_value=resubmit_resp,
            ),
            patch("app.routers.essays._compute_embedding_task", failing_task),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.post(
                self._url(essay_id),
                files=[("file", ("revised.txt", BytesIO(b"Revised essay text."), "text/plain"))],
            )

        assert resp.status_code == 201, resp.text
