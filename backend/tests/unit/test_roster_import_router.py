"""Unit tests for CSV roster import endpoints.

Tests cover:
- POST /api/v1/classes/{id}/students/import     — valid CSV, invalid CSV (422),
  class not found (404), wrong teacher (403), auth required (401)
- POST /api/v1/classes/{id}/students/import/confirm — happy path, 404, 403, auth

No real PostgreSQL.  All service calls are mocked.  No student PII in fixtures.
"""

from __future__ import annotations

import io
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from app.dependencies import get_current_teacher
from app.exceptions import ForbiddenError, NotFoundError, ValidationError
from app.main import create_app
from app.schemas.roster_import import ImportRowStatus
from app.services.roster_import import DiffRow

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_teacher(teacher_id: uuid.UUID | None = None) -> MagicMock:
    teacher = MagicMock()
    teacher.id = teacher_id or uuid.uuid4()
    teacher.email = "teacher@school.edu"
    teacher.email_verified = True
    return teacher


def _app_with_teacher(teacher: MagicMock | None = None) -> object:
    teacher = teacher or _make_teacher()
    app = create_app()
    app.dependency_overrides[get_current_teacher] = lambda: teacher  # type: ignore[attr-defined]
    return app


def _make_diff_row(
    row_number: int = 1,
    full_name: str = "Student One",
    external_id: str | None = None,
    status: ImportRowStatus = ImportRowStatus.NEW,
    message: str | None = None,
    existing_student_id: uuid.UUID | None = None,
) -> DiffRow:
    return DiffRow(
        row_number=row_number,
        full_name=full_name,
        external_id=external_id,
        status=status,
        message=message,
        existing_student_id=existing_student_id,
    )


def _csv_bytes(*rows: str, header: str = "full_name,external_id") -> bytes:
    lines = [header] + list(rows)
    return "\n".join(lines).encode()


# ---------------------------------------------------------------------------
# POST /api/v1/classes/{classId}/students/import
# ---------------------------------------------------------------------------


class TestImportStudents:
    def test_returns_200_with_diff_for_valid_csv(self) -> None:
        teacher = _make_teacher()
        class_id = uuid.uuid4()
        diff_row = _make_diff_row(row_number=1, full_name="Student One")
        app = _app_with_teacher(teacher)

        with (
            patch(
                "app.routers.classes.parse_csv_roster",
                return_value=MagicMock(rows=[MagicMock()], errors=[]),
            ),
            patch(
                "app.routers.classes.build_import_diff",
                new_callable=AsyncMock,
                return_value=[diff_row],
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            csv_content = _csv_bytes("Student One,ext-001")
            resp = client.post(
                f"/api/v1/classes/{class_id}/students/import",
                files={"file": ("roster.csv", io.BytesIO(csv_content), "text/csv")},
            )

        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["new_count"] == 1
        assert data["updated_count"] == 0
        assert data["skipped_count"] == 0
        assert data["error_count"] == 0
        assert len(data["rows"]) == 1
        assert data["rows"][0]["status"] == "new"

    def test_includes_error_rows_from_parse_result(self) -> None:
        teacher = _make_teacher()
        class_id = uuid.uuid4()
        error_row = _make_diff_row(
            row_number=1,
            full_name="",
            status=ImportRowStatus.ERROR,
            message="Row is missing a required full_name value.",
        )
        valid_diff_row = _make_diff_row(row_number=2, full_name="Student Two")
        app = _app_with_teacher(teacher)

        with (
            patch(
                "app.routers.classes.parse_csv_roster",
                return_value=MagicMock(
                    rows=[MagicMock()],
                    errors=[error_row],
                ),
            ),
            patch(
                "app.routers.classes.build_import_diff",
                new_callable=AsyncMock,
                return_value=[valid_diff_row],
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            csv_content = _csv_bytes("", "Student Two,ext-002")
            resp = client.post(
                f"/api/v1/classes/{class_id}/students/import",
                files={"file": ("roster.csv", io.BytesIO(csv_content), "text/csv")},
            )

        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["error_count"] == 1
        assert data["new_count"] == 1
        # rows are sorted by row_number
        assert data["rows"][0]["row_number"] == 1
        assert data["rows"][1]["row_number"] == 2

    def test_returns_422_when_parse_raises_validation_error(self) -> None:
        teacher = _make_teacher()
        class_id = uuid.uuid4()
        app = _app_with_teacher(teacher)

        with (
            patch(
                "app.routers.classes.parse_csv_roster",
                side_effect=ValidationError("CSV must contain a 'full_name' column.", field="file"),
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.post(
                f"/api/v1/classes/{class_id}/students/import",
                files={"file": ("roster.csv", io.BytesIO(b"external_id\next-001\n"), "text/csv")},
            )

        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "VALIDATION_ERROR"

    def test_returns_404_when_class_not_found(self) -> None:
        teacher = _make_teacher()
        class_id = uuid.uuid4()
        app = _app_with_teacher(teacher)

        with (
            patch(
                "app.routers.classes.parse_csv_roster",
                return_value=MagicMock(rows=[], errors=[]),
            ),
            patch(
                "app.routers.classes.build_import_diff",
                new_callable=AsyncMock,
                side_effect=NotFoundError("Class not found."),
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.post(
                f"/api/v1/classes/{class_id}/students/import",
                files={"file": ("roster.csv", io.BytesIO(b"full_name\n"), "text/csv")},
            )

        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "NOT_FOUND"

    def test_returns_403_for_other_teachers_class(self) -> None:
        teacher = _make_teacher()
        class_id = uuid.uuid4()
        app = _app_with_teacher(teacher)

        with (
            patch(
                "app.routers.classes.parse_csv_roster",
                return_value=MagicMock(rows=[], errors=[]),
            ),
            patch(
                "app.routers.classes.build_import_diff",
                new_callable=AsyncMock,
                side_effect=ForbiddenError("You do not have access to this class."),
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.post(
                f"/api/v1/classes/{class_id}/students/import",
                files={"file": ("roster.csv", io.BytesIO(b"full_name\n"), "text/csv")},
            )

        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "FORBIDDEN"

    def test_requires_authentication(self) -> None:
        app = create_app()
        class_id = uuid.uuid4()
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(
                f"/api/v1/classes/{class_id}/students/import",
                files={"file": ("roster.csv", io.BytesIO(b"full_name\n"), "text/csv")},
            )
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "UNAUTHORIZED"

    def test_diff_rows_sorted_by_row_number(self) -> None:
        teacher = _make_teacher()
        class_id = uuid.uuid4()
        # Return rows out of order from the service
        diff_rows = [
            _make_diff_row(row_number=3, full_name="Student C"),
            _make_diff_row(row_number=1, full_name="Student A"),
            _make_diff_row(row_number=2, full_name="Student B"),
        ]
        app = _app_with_teacher(teacher)

        with (
            patch(
                "app.routers.classes.parse_csv_roster",
                return_value=MagicMock(rows=[MagicMock() for _ in range(3)], errors=[]),
            ),
            patch(
                "app.routers.classes.build_import_diff",
                new_callable=AsyncMock,
                return_value=diff_rows,
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            csv_content = _csv_bytes("Student A", "Student B", "Student C")
            resp = client.post(
                f"/api/v1/classes/{class_id}/students/import",
                files={"file": ("roster.csv", io.BytesIO(csv_content), "text/csv")},
            )

        assert resp.status_code == 200, resp.text
        row_numbers = [r["row_number"] for r in resp.json()["data"]["rows"]]
        assert row_numbers == [1, 2, 3]

    def test_counts_are_accurate_across_statuses(self) -> None:
        teacher = _make_teacher()
        class_id = uuid.uuid4()
        diff_rows = [
            _make_diff_row(row_number=1, status=ImportRowStatus.NEW),
            _make_diff_row(row_number=2, status=ImportRowStatus.UPDATED),
            _make_diff_row(row_number=3, status=ImportRowStatus.SKIPPED),
            _make_diff_row(row_number=4, status=ImportRowStatus.NEW),
        ]
        app = _app_with_teacher(teacher)

        with (
            patch(
                "app.routers.classes.parse_csv_roster",
                return_value=MagicMock(rows=[MagicMock() for _ in range(4)], errors=[]),
            ),
            patch(
                "app.routers.classes.build_import_diff",
                new_callable=AsyncMock,
                return_value=diff_rows,
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            csv_content = _csv_bytes("A", "B", "C", "D")
            resp = client.post(
                f"/api/v1/classes/{class_id}/students/import",
                files={"file": ("roster.csv", io.BytesIO(csv_content), "text/csv")},
            )

        data = resp.json()["data"]
        assert data["new_count"] == 2
        assert data["updated_count"] == 1
        assert data["skipped_count"] == 1
        assert data["error_count"] == 0


# ---------------------------------------------------------------------------
# POST /api/v1/classes/{classId}/students/import/confirm
# ---------------------------------------------------------------------------


class TestConfirmImport:
    def test_returns_200_with_commit_counts(self) -> None:
        teacher = _make_teacher()
        class_id = uuid.uuid4()
        app = _app_with_teacher(teacher)

        with (
            patch(
                "app.routers.classes.commit_roster_import",
                new_callable=AsyncMock,
                return_value={"created": 3, "updated": 1, "skipped": 0},
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.post(
                f"/api/v1/classes/{class_id}/students/import/confirm",
                json={
                    "rows": [
                        {"row_number": 1, "full_name": "Student One", "external_id": None},
                        {"row_number": 2, "full_name": "Student Two", "external_id": "ext-002"},
                    ]
                },
            )

        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["created"] == 3
        assert data["updated"] == 1
        assert data["skipped"] == 0

    def test_returns_404_when_class_not_found(self) -> None:
        teacher = _make_teacher()
        class_id = uuid.uuid4()
        app = _app_with_teacher(teacher)

        with (
            patch(
                "app.routers.classes.commit_roster_import",
                new_callable=AsyncMock,
                side_effect=NotFoundError("Class not found."),
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.post(
                f"/api/v1/classes/{class_id}/students/import/confirm",
                json={"rows": [{"row_number": 1, "full_name": "Student One"}]},
            )

        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "NOT_FOUND"

    def test_returns_403_for_other_teachers_class(self) -> None:
        teacher = _make_teacher()
        class_id = uuid.uuid4()
        app = _app_with_teacher(teacher)

        with (
            patch(
                "app.routers.classes.commit_roster_import",
                new_callable=AsyncMock,
                side_effect=ForbiddenError("You do not have access to this class."),
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.post(
                f"/api/v1/classes/{class_id}/students/import/confirm",
                json={"rows": [{"row_number": 1, "full_name": "Student One"}]},
            )

        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "FORBIDDEN"

    def test_requires_authentication(self) -> None:
        app = create_app()
        class_id = uuid.uuid4()
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(
                f"/api/v1/classes/{class_id}/students/import/confirm",
                json={"rows": [{"row_number": 1, "full_name": "Student One"}]},
            )
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "UNAUTHORIZED"

    def test_returns_422_when_rows_empty(self) -> None:
        teacher = _make_teacher()
        class_id = uuid.uuid4()
        app = _app_with_teacher(teacher)

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(
                f"/api/v1/classes/{class_id}/students/import/confirm",
                json={"rows": []},
            )

        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "VALIDATION_ERROR"

    def test_returns_422_when_full_name_empty(self) -> None:
        teacher = _make_teacher()
        class_id = uuid.uuid4()
        app = _app_with_teacher(teacher)

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(
                f"/api/v1/classes/{class_id}/students/import/confirm",
                json={"rows": [{"row_number": 1, "full_name": ""}]},
            )

        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "VALIDATION_ERROR"

    def test_passes_rows_to_commit_service(self) -> None:
        """Verify that the router correctly maps request rows to ParsedRow objects."""
        teacher = _make_teacher()
        class_id = uuid.uuid4()
        app = _app_with_teacher(teacher)

        commit_mock = AsyncMock(return_value={"created": 1, "updated": 0, "skipped": 0})
        with (
            patch("app.routers.classes.commit_roster_import", commit_mock),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.post(
                f"/api/v1/classes/{class_id}/students/import/confirm",
                json={
                    "rows": [
                        {"row_number": 1, "full_name": "Student One", "external_id": "ext-001"},
                    ]
                },
            )

        assert resp.status_code == 200, resp.text
        commit_mock.assert_called_once()
        _, kwargs_teacher, kwargs_class, kwargs_rows = commit_mock.call_args[0]
        assert kwargs_rows[0].full_name == "Student One"
        assert kwargs_rows[0].external_id == "ext-001"
        assert kwargs_rows[0].row_number == 1
