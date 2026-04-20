"""Unit tests for the rubric templates router endpoints.

Tests cover:
- GET  /api/v1/rubric-templates           — list, auth required
- GET  /api/v1/rubric-templates/{id}      — get single template, 403, 404, auth required
- POST /api/v1/rubric-templates           — create, 403, 404, auth required

No real PostgreSQL.  All DB / service calls are mocked.  No student PII.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
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


def _make_rubric_orm(
    teacher_id: uuid.UUID | None = None,
    rubric_id: uuid.UUID | None = None,
    name: str = "Test Rubric",
    is_template: bool = True,
) -> MagicMock:
    rubric = MagicMock()
    rubric.id = rubric_id or uuid.uuid4()
    rubric.teacher_id = teacher_id  # None for system templates
    rubric.name = name
    rubric.description = "A test rubric"
    rubric.is_template = is_template
    rubric.created_at = datetime.now(UTC)
    rubric.updated_at = datetime.now(UTC)
    rubric.deleted_at = None
    return rubric


def _make_criterion_orm(
    rubric_id: uuid.UUID | None = None,
    display_order: int = 0,
    weight: Decimal = Decimal("100"),
) -> MagicMock:
    c = MagicMock()
    c.id = uuid.uuid4()
    c.rubric_id = rubric_id or uuid.uuid4()
    c.name = "Thesis"
    c.description = "Does the essay have a clear thesis?"
    c.weight = weight
    c.min_score = 1
    c.max_score = 5
    c.display_order = display_order
    c.anchor_descriptions = None
    return c


def _app_with_teacher(teacher: MagicMock | None = None) -> object:
    teacher = teacher or _make_teacher()
    app = create_app()
    app.dependency_overrides[get_current_teacher] = lambda: teacher  # type: ignore[attr-defined]
    return app


# ---------------------------------------------------------------------------
# GET /api/v1/rubric-templates
# ---------------------------------------------------------------------------


class TestListRubricTemplates:
    def test_returns_empty_list(self) -> None:
        app = _app_with_teacher()
        with (
            patch(
                "app.routers.rubric_templates.list_rubric_templates",
                new_callable=AsyncMock,
                return_value=[],
            ),
            TestClient(app, raise_server_exceptions=False) as client,  # type: ignore[arg-type]
        ):
            resp = client.get("/api/v1/rubric-templates")

        assert resp.status_code == 200, resp.text
        assert resp.json()["data"] == []

    def test_returns_system_and_personal_templates(self) -> None:
        teacher = _make_teacher()
        system_rubric = _make_rubric_orm(teacher_id=None, name="5-Paragraph Essay")
        personal_rubric = _make_rubric_orm(teacher_id=teacher.id, name="My Template")
        app = _app_with_teacher(teacher)

        with (
            patch(
                "app.routers.rubric_templates.list_rubric_templates",
                new_callable=AsyncMock,
                return_value=[
                    (system_rubric, 1, True),
                    (personal_rubric, 1, False),
                ],
            ),
            TestClient(app, raise_server_exceptions=False) as client,  # type: ignore[arg-type]
        ):
            resp = client.get("/api/v1/rubric-templates")

        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert len(data) == 2
        assert data[0]["name"] == system_rubric.name
        assert data[0]["is_system"] is True
        assert data[0]["criterion_count"] == 1
        assert data[1]["name"] == personal_rubric.name
        assert data[1]["is_system"] is False

    def test_returns_401_without_auth(self) -> None:
        app = create_app()
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/api/v1/rubric-templates")

        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "UNAUTHORIZED"


# ---------------------------------------------------------------------------
# POST /api/v1/rubric-templates
# ---------------------------------------------------------------------------


class TestSaveRubricAsTemplate:
    def test_creates_template_and_returns_201(self) -> None:
        teacher = _make_teacher()
        source_id = uuid.uuid4()
        template_rubric = _make_rubric_orm(teacher_id=teacher.id, name="My Template")
        criterion = _make_criterion_orm(rubric_id=template_rubric.id)
        app = _app_with_teacher(teacher)

        with (
            patch(
                "app.routers.rubric_templates.save_rubric_as_template",
                new_callable=AsyncMock,
                return_value=(template_rubric, [criterion]),
            ),
            TestClient(app, raise_server_exceptions=False) as client,  # type: ignore[arg-type]
        ):
            resp = client.post(
                "/api/v1/rubric-templates",
                json={"rubric_id": str(source_id)},
            )

        assert resp.status_code == 201, resp.text
        data = resp.json()["data"]
        assert data["name"] == template_rubric.name
        assert data["is_system"] is False
        assert len(data["criteria"]) == 1

    def test_saves_with_name_override(self) -> None:
        teacher = _make_teacher()
        source_id = uuid.uuid4()
        template_rubric = _make_rubric_orm(teacher_id=teacher.id, name="Custom Name")
        app = _app_with_teacher(teacher)

        mock_save = AsyncMock(return_value=(template_rubric, []))
        with (
            patch("app.routers.rubric_templates.save_rubric_as_template", mock_save),
            TestClient(app, raise_server_exceptions=False) as client,  # type: ignore[arg-type]
        ):
            resp = client.post(
                "/api/v1/rubric-templates",
                json={"rubric_id": str(source_id), "name": "Custom Name"},
            )

        assert resp.status_code == 201, resp.text
        # Verify the name override was passed to the service.
        call_kwargs = mock_save.call_args.kwargs
        assert call_kwargs["name"] == "Custom Name"

    def test_returns_404_when_source_not_found(self) -> None:
        teacher = _make_teacher()
        app = _app_with_teacher(teacher)

        with (
            patch(
                "app.routers.rubric_templates.save_rubric_as_template",
                new_callable=AsyncMock,
                side_effect=NotFoundError("Rubric not found."),
            ),
            TestClient(app, raise_server_exceptions=False) as client,  # type: ignore[arg-type]
        ):
            resp = client.post(
                "/api/v1/rubric-templates",
                json={"rubric_id": str(uuid.uuid4())},
            )

        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "NOT_FOUND"

    def test_returns_403_for_cross_teacher_source(self) -> None:
        teacher = _make_teacher()
        app = _app_with_teacher(teacher)

        with (
            patch(
                "app.routers.rubric_templates.save_rubric_as_template",
                new_callable=AsyncMock,
                side_effect=ForbiddenError("You do not have access to this rubric."),
            ),
            TestClient(app, raise_server_exceptions=False) as client,  # type: ignore[arg-type]
        ):
            resp = client.post(
                "/api/v1/rubric-templates",
                json={"rubric_id": str(uuid.uuid4())},
            )

        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "FORBIDDEN"

    def test_returns_422_for_missing_rubric_id(self) -> None:
        teacher = _make_teacher()
        app = _app_with_teacher(teacher)

        with TestClient(app, raise_server_exceptions=False) as client:  # type: ignore[arg-type]
            resp = client.post("/api/v1/rubric-templates", json={})

        assert resp.status_code == 422

    def test_returns_401_without_auth(self) -> None:
        app = create_app()
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(
                "/api/v1/rubric-templates",
                json={"rubric_id": str(uuid.uuid4())},
            )

        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET /api/v1/rubric-templates/{template_id}
# ---------------------------------------------------------------------------


class TestGetRubricTemplate:
    def test_returns_system_template(self) -> None:
        teacher = _make_teacher()
        template_id = uuid.uuid4()
        system_rubric = _make_rubric_orm(
            teacher_id=None, rubric_id=template_id, name="5-Paragraph Essay"
        )
        criterion = _make_criterion_orm(rubric_id=template_id)
        app = _app_with_teacher(teacher)

        with (
            patch(
                "app.routers.rubric_templates.get_rubric_template",
                new_callable=AsyncMock,
                return_value=(system_rubric, [criterion], True),
            ),
            TestClient(app, raise_server_exceptions=False) as client,  # type: ignore[arg-type]
        ):
            resp = client.get(f"/api/v1/rubric-templates/{template_id}")

        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["name"] == system_rubric.name
        assert data["is_system"] is True
        assert len(data["criteria"]) == 1

    def test_returns_404_when_not_found(self) -> None:
        teacher = _make_teacher()
        app = _app_with_teacher(teacher)

        with (
            patch(
                "app.routers.rubric_templates.get_rubric_template",
                new_callable=AsyncMock,
                side_effect=NotFoundError("Template not found."),
            ),
            TestClient(app, raise_server_exceptions=False) as client,  # type: ignore[arg-type]
        ):
            resp = client.get(f"/api/v1/rubric-templates/{uuid.uuid4()}")

        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "NOT_FOUND"

    def test_returns_403_for_cross_teacher_personal(self) -> None:
        teacher = _make_teacher()
        app = _app_with_teacher(teacher)

        with (
            patch(
                "app.routers.rubric_templates.get_rubric_template",
                new_callable=AsyncMock,
                side_effect=ForbiddenError("You do not have access to this template."),
            ),
            TestClient(app, raise_server_exceptions=False) as client,  # type: ignore[arg-type]
        ):
            resp = client.get(f"/api/v1/rubric-templates/{uuid.uuid4()}")

        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "FORBIDDEN"

    def test_returns_401_without_auth(self) -> None:
        app = create_app()
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get(f"/api/v1/rubric-templates/{uuid.uuid4()}")

        assert resp.status_code == 401
