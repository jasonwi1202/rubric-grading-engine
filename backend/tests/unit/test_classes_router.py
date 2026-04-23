"""Unit tests for the classes router endpoints.

Tests cover:
- GET  /api/v1/classes               — list, auth required, filters
- POST /api/v1/classes               — create, auth required, 201
- GET  /api/v1/classes/{id}          — get, 404, 403, auth required
- PATCH /api/v1/classes/{id}         — update, 403, 404, auth required
- POST /api/v1/classes/{id}/archive  — archive, 403, 404, auth required
- Cross-teacher access returns 403 (tenant isolation)

No real PostgreSQL.  All DB / service calls are mocked.  No student PII.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from app.dependencies import get_current_teacher
from app.exceptions import ForbiddenError, NotFoundError
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


def _make_class_orm(
    teacher_id: uuid.UUID | None = None,
    class_id: uuid.UUID | None = None,
    name: str = "Honors English",
    subject: str = "English",
    grade_level: str = "10",
    academic_year: str = "2025-26",
    is_archived: bool = False,
) -> MagicMock:
    cls = MagicMock()
    cls.id = class_id or uuid.uuid4()
    cls.teacher_id = teacher_id or uuid.uuid4()
    cls.name = name
    cls.subject = subject
    cls.grade_level = grade_level
    cls.academic_year = academic_year
    cls.is_archived = is_archived
    cls.created_at = datetime.now(UTC)
    return cls


def _app_with_teacher(teacher: MagicMock | None = None) -> object:
    teacher = teacher or _make_teacher()
    app = create_app()
    app.dependency_overrides[get_current_teacher] = lambda: teacher  # type: ignore[attr-defined]
    return app


# ---------------------------------------------------------------------------
# GET /api/v1/classes
# ---------------------------------------------------------------------------


class TestListClasses:
    def test_returns_empty_list(self) -> None:
        app = _app_with_teacher()
        with (
            patch(
                "app.routers.classes.list_classes",
                new_callable=AsyncMock,
                return_value=[],
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.get("/api/v1/classes")

        assert resp.status_code == 200, resp.text
        assert resp.json()["data"] == []

    def test_returns_list_of_classes(self) -> None:
        teacher = _make_teacher()
        cls1 = _make_class_orm(teacher_id=teacher.id, name="Math 101")
        cls2 = _make_class_orm(teacher_id=teacher.id, name="Science 201")
        app = _app_with_teacher(teacher)
        with (
            patch(
                "app.routers.classes.list_classes",
                new_callable=AsyncMock,
                return_value=[cls1, cls2],
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.get("/api/v1/classes")

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert len(data) == 2
        assert data[0]["name"] == "Math 101"
        assert data[1]["name"] == "Science 201"

    def test_passes_filters_to_service(self) -> None:
        teacher = _make_teacher()
        cls1 = _make_class_orm(teacher_id=teacher.id, academic_year="2025-26")
        app = _app_with_teacher(teacher)
        mock_list = AsyncMock(return_value=[cls1])
        with (
            patch("app.routers.classes.list_classes", mock_list),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.get("/api/v1/classes?academic_year=2025-26&is_archived=false")

        assert resp.status_code == 200
        mock_list.assert_called_once()
        call_kwargs = mock_list.call_args.kwargs
        assert call_kwargs["academic_year"] == "2025-26"
        assert call_kwargs["is_archived"] is False

    def test_requires_authentication(self) -> None:
        app = create_app()
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/api/v1/classes")
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "UNAUTHORIZED"


# ---------------------------------------------------------------------------
# POST /api/v1/classes
# ---------------------------------------------------------------------------


class TestCreateClass:
    def test_creates_class_and_returns_201(self) -> None:
        teacher = _make_teacher()
        new_cls = _make_class_orm(
            teacher_id=teacher.id,
            name="AP History",
            subject="History",
            grade_level="11",
            academic_year="2025-26",
        )
        app = _app_with_teacher(teacher)
        with (
            patch(
                "app.routers.classes.create_class",
                new_callable=AsyncMock,
                return_value=new_cls,
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.post(
                "/api/v1/classes",
                json={
                    "name": "AP History",
                    "subject": "History",
                    "grade_level": "11",
                    "academic_year": "2025-26",
                },
            )

        assert resp.status_code == 201, resp.text
        data = resp.json()["data"]
        assert data["name"] == "AP History"
        assert data["subject"] == "History"
        assert data["academic_year"] == "2025-26"
        assert data["is_archived"] is False

    def test_returns_422_when_name_missing(self) -> None:
        app = _app_with_teacher()
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(
                "/api/v1/classes",
                json={
                    "subject": "History",
                    "grade_level": "11",
                    "academic_year": "2025-26",
                },
            )
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "VALIDATION_ERROR"

    def test_requires_authentication(self) -> None:
        app = create_app()
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(
                "/api/v1/classes",
                json={
                    "name": "AP History",
                    "subject": "History",
                    "grade_level": "11",
                    "academic_year": "2025-26",
                },
            )
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "UNAUTHORIZED"


# ---------------------------------------------------------------------------
# GET /api/v1/classes/{classId}
# ---------------------------------------------------------------------------


class TestGetClass:
    def test_returns_class(self) -> None:
        teacher = _make_teacher()
        cls = _make_class_orm(teacher_id=teacher.id)
        app = _app_with_teacher(teacher)
        with (
            patch(
                "app.routers.classes.get_class",
                new_callable=AsyncMock,
                return_value=cls,
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.get(f"/api/v1/classes/{cls.id}")

        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["id"] == str(cls.id)

    def test_returns_404_when_not_found(self) -> None:
        teacher = _make_teacher()
        class_id = uuid.uuid4()
        app = _app_with_teacher(teacher)
        with (
            patch(
                "app.routers.classes.get_class",
                new_callable=AsyncMock,
                side_effect=NotFoundError("Class not found."),
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.get(f"/api/v1/classes/{class_id}")

        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "NOT_FOUND"

    def test_returns_403_for_other_teachers_class(self) -> None:
        teacher = _make_teacher()
        class_id = uuid.uuid4()
        app = _app_with_teacher(teacher)
        with (
            patch(
                "app.routers.classes.get_class",
                new_callable=AsyncMock,
                side_effect=ForbiddenError("You do not have access to this class."),
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.get(f"/api/v1/classes/{class_id}")

        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "FORBIDDEN"

    def test_requires_authentication(self) -> None:
        app = create_app()
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get(f"/api/v1/classes/{uuid.uuid4()}")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# PATCH /api/v1/classes/{classId}
# ---------------------------------------------------------------------------


class TestPatchClass:
    def test_updates_class(self) -> None:
        teacher = _make_teacher()
        cls = _make_class_orm(teacher_id=teacher.id, name="Updated Name")
        app = _app_with_teacher(teacher)
        with (
            patch(
                "app.routers.classes.update_class",
                new_callable=AsyncMock,
                return_value=cls,
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.patch(
                f"/api/v1/classes/{cls.id}",
                json={"name": "Updated Name"},
            )

        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["name"] == "Updated Name"

    def test_returns_404_when_not_found(self) -> None:
        teacher = _make_teacher()
        class_id = uuid.uuid4()
        app = _app_with_teacher(teacher)
        with (
            patch(
                "app.routers.classes.update_class",
                new_callable=AsyncMock,
                side_effect=NotFoundError("Class not found."),
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.patch(f"/api/v1/classes/{class_id}", json={"name": "X"})

        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "NOT_FOUND"

    def test_returns_403_for_other_teachers_class(self) -> None:
        teacher = _make_teacher()
        class_id = uuid.uuid4()
        app = _app_with_teacher(teacher)
        with (
            patch(
                "app.routers.classes.update_class",
                new_callable=AsyncMock,
                side_effect=ForbiddenError("You do not have access to this class."),
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.patch(f"/api/v1/classes/{class_id}", json={"name": "X"})

        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "FORBIDDEN"

    def test_requires_authentication(self) -> None:
        app = create_app()
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.patch(f"/api/v1/classes/{uuid.uuid4()}", json={"name": "X"})
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# POST /api/v1/classes/{classId}/archive
# ---------------------------------------------------------------------------


class TestArchiveClass:
    def test_archives_class(self) -> None:
        teacher = _make_teacher()
        cls = _make_class_orm(teacher_id=teacher.id, is_archived=True)
        app = _app_with_teacher(teacher)
        with (
            patch(
                "app.routers.classes.archive_class",
                new_callable=AsyncMock,
                return_value=cls,
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.post(f"/api/v1/classes/{cls.id}/archive")

        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["is_archived"] is True

    def test_returns_404_when_not_found(self) -> None:
        teacher = _make_teacher()
        class_id = uuid.uuid4()
        app = _app_with_teacher(teacher)
        with (
            patch(
                "app.routers.classes.archive_class",
                new_callable=AsyncMock,
                side_effect=NotFoundError("Class not found."),
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.post(f"/api/v1/classes/{class_id}/archive")

        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "NOT_FOUND"

    def test_returns_403_for_other_teachers_class(self) -> None:
        teacher = _make_teacher()
        class_id = uuid.uuid4()
        app = _app_with_teacher(teacher)
        with (
            patch(
                "app.routers.classes.archive_class",
                new_callable=AsyncMock,
                side_effect=ForbiddenError("You do not have access to this class."),
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.post(f"/api/v1/classes/{class_id}/archive")

        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "FORBIDDEN"

    def test_requires_authentication(self) -> None:
        app = create_app()
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(f"/api/v1/classes/{uuid.uuid4()}/archive")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Tenant isolation
# ---------------------------------------------------------------------------


class TestClassTenantIsolation:
    def test_list_only_returns_own_classes(self) -> None:
        """Service is called with the authenticated teacher's id."""
        teacher_a = _make_teacher()
        app = _app_with_teacher(teacher_a)
        mock_list = AsyncMock(return_value=[])
        with (
            patch("app.routers.classes.list_classes", mock_list),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.get("/api/v1/classes")

        assert resp.status_code == 200
        mock_list.assert_called_once()
        assert mock_list.call_args.kwargs["teacher_id"] == teacher_a.id

    def test_get_other_teacher_class_returns_403(self) -> None:
        """Attempting to GET another teacher's class returns 403."""
        teacher_b = _make_teacher()
        class_id = uuid.uuid4()
        app = _app_with_teacher(teacher_b)
        with (
            patch(
                "app.routers.classes.get_class",
                new_callable=AsyncMock,
                side_effect=ForbiddenError("You do not have access to this class."),
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.get(f"/api/v1/classes/{class_id}")

        assert resp.status_code == 403, resp.text
        assert resp.json()["error"]["code"] == "FORBIDDEN"

    def test_archive_other_teacher_class_returns_403(self) -> None:
        """Attempting to archive another teacher's class returns 403."""
        teacher_b = _make_teacher()
        class_id = uuid.uuid4()
        app = _app_with_teacher(teacher_b)
        with (
            patch(
                "app.routers.classes.archive_class",
                new_callable=AsyncMock,
                side_effect=ForbiddenError("You do not have access to this class."),
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.post(f"/api/v1/classes/{class_id}/archive")

        assert resp.status_code == 403, resp.text
        assert resp.json()["error"]["code"] == "FORBIDDEN"
