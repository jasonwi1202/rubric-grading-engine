"""Unit tests for the rubric router endpoints.

Tests cover:
- GET  /api/v1/rubrics               — list, auth required
- POST /api/v1/rubrics               — create, weight-sum validation, auth required
- GET  /api/v1/rubrics/{id}          — get, 404, 403, auth required
- PATCH /api/v1/rubrics/{id}         — update, weight-sum validation, 403, auth required
- DELETE /api/v1/rubrics/{id}        — delete, 409 if in use, 403, auth required
- POST /api/v1/rubrics/{id}/duplicate — duplicate, 403, auth required

No real PostgreSQL.  All DB / service calls are mocked.  No student PII.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from app.dependencies import get_current_teacher
from app.exceptions import ForbiddenError, NotFoundError, RubricInUseError, RubricWeightInvalidError
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
) -> MagicMock:
    rubric = MagicMock()
    rubric.id = rubric_id or uuid.uuid4()
    rubric.teacher_id = teacher_id or uuid.uuid4()
    rubric.name = name
    rubric.description = None
    rubric.is_template = False
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


def _valid_criteria_payload() -> list[dict[str, object]]:
    return [
        {"name": "Thesis", "weight": 60, "min_score": 1, "max_score": 5},
        {"name": "Evidence", "weight": 40, "min_score": 1, "max_score": 5},
    ]


def _app_with_teacher(teacher: MagicMock | None = None) -> object:
    teacher = teacher or _make_teacher()
    app = create_app()
    app.dependency_overrides[get_current_teacher] = lambda: teacher  # type: ignore[attr-defined]
    return app


# ---------------------------------------------------------------------------
# GET /api/v1/rubrics
# ---------------------------------------------------------------------------


class TestListRubrics:
    def test_returns_empty_list(self) -> None:
        app = _app_with_teacher()
        with (
            patch(
                "app.routers.rubrics.list_rubrics",
                new_callable=AsyncMock,
                return_value=[],
            ),
            TestClient(app, raise_server_exceptions=False) as client,  # type: ignore[arg-type]
        ):
            resp = client.get("/api/v1/rubrics")

        assert resp.status_code == 200, resp.text
        assert resp.json()["data"] == []

    def test_returns_rubric_list_with_criterion_count(self) -> None:
        teacher = _make_teacher()
        rubric = _make_rubric_orm(teacher_id=teacher.id)
        criterion = _make_criterion_orm(rubric_id=rubric.id)
        app = _app_with_teacher(teacher)

        with (
            patch(
                "app.routers.rubrics.list_rubrics",
                new_callable=AsyncMock,
                return_value=[(rubric, [criterion])],
            ),
            TestClient(app, raise_server_exceptions=False) as client,  # type: ignore[arg-type]
        ):
            resp = client.get("/api/v1/rubrics")

        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert len(data) == 1
        assert data[0]["name"] == rubric.name
        assert data[0]["criterion_count"] == 1

    def test_returns_401_without_auth(self) -> None:
        app = create_app()
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/api/v1/rubrics")

        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "UNAUTHORIZED"


# ---------------------------------------------------------------------------
# POST /api/v1/rubrics
# ---------------------------------------------------------------------------


class TestCreateRubric:
    def test_creates_rubric_and_returns_201(self) -> None:
        teacher = _make_teacher()
        rubric = _make_rubric_orm(teacher_id=teacher.id)
        criterion = _make_criterion_orm(rubric_id=rubric.id, weight=Decimal("60"))
        criterion2 = _make_criterion_orm(rubric_id=rubric.id, weight=Decimal("40"), display_order=1)
        app = _app_with_teacher(teacher)

        with (
            patch(
                "app.routers.rubrics.create_rubric",
                new_callable=AsyncMock,
                return_value=(rubric, [criterion, criterion2]),
            ),
            TestClient(app, raise_server_exceptions=False) as client,  # type: ignore[arg-type]
        ):
            resp = client.post(
                "/api/v1/rubrics",
                json={"name": "My Rubric", "criteria": _valid_criteria_payload()},
            )

        assert resp.status_code == 201, resp.text
        data = resp.json()["data"]
        assert data["name"] == rubric.name
        assert len(data["criteria"]) == 2

    def test_returns_422_for_invalid_weight_sum(self) -> None:
        teacher = _make_teacher()
        app = _app_with_teacher(teacher)

        with (
            patch(
                "app.routers.rubrics.create_rubric",
                new_callable=AsyncMock,
                side_effect=RubricWeightInvalidError(
                    "Criterion weights must sum to 100. Got 50.", field="criteria"
                ),
            ),
            TestClient(app, raise_server_exceptions=False) as client,  # type: ignore[arg-type]
        ):
            resp = client.post(
                "/api/v1/rubrics",
                json={
                    "name": "Bad Rubric",
                    "criteria": [{"name": "Thesis", "weight": 50, "min_score": 1, "max_score": 5}],
                },
            )

        assert resp.status_code == 422, resp.text
        assert resp.json()["error"]["code"] == "RUBRIC_WEIGHT_INVALID"

    def test_returns_422_for_missing_criteria(self) -> None:
        teacher = _make_teacher()
        app = _app_with_teacher(teacher)
        with TestClient(app, raise_server_exceptions=False) as client:  # type: ignore[arg-type]
            resp = client.post(
                "/api/v1/rubrics",
                json={"name": "Bad Rubric", "criteria": []},
            )
        assert resp.status_code == 422

    def test_returns_401_without_auth(self) -> None:
        app = create_app()
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(
                "/api/v1/rubrics",
                json={"name": "X", "criteria": _valid_criteria_payload()},
            )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET /api/v1/rubrics/{rubric_id}
# ---------------------------------------------------------------------------


class TestGetRubric:
    def test_returns_rubric_with_criteria(self) -> None:
        teacher = _make_teacher()
        rubric_id = uuid.uuid4()
        rubric = _make_rubric_orm(teacher_id=teacher.id, rubric_id=rubric_id)
        criterion = _make_criterion_orm(rubric_id=rubric_id)
        app = _app_with_teacher(teacher)

        with (
            patch(
                "app.routers.rubrics.get_rubric",
                new_callable=AsyncMock,
                return_value=(rubric, [criterion]),
            ),
            TestClient(app, raise_server_exceptions=False) as client,  # type: ignore[arg-type]
        ):
            resp = client.get(f"/api/v1/rubrics/{rubric_id}")

        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["id"] == str(rubric_id)
        assert len(data["criteria"]) == 1

    def test_returns_404_when_not_found(self) -> None:
        teacher = _make_teacher()
        rubric_id = uuid.uuid4()
        app = _app_with_teacher(teacher)

        with (
            patch(
                "app.routers.rubrics.get_rubric",
                new_callable=AsyncMock,
                side_effect=NotFoundError("Rubric not found."),
            ),
            TestClient(app, raise_server_exceptions=False) as client,  # type: ignore[arg-type]
        ):
            resp = client.get(f"/api/v1/rubrics/{rubric_id}")

        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "NOT_FOUND"

    def test_returns_403_for_cross_teacher_access(self) -> None:
        teacher = _make_teacher()
        rubric_id = uuid.uuid4()
        app = _app_with_teacher(teacher)

        with (
            patch(
                "app.routers.rubrics.get_rubric",
                new_callable=AsyncMock,
                side_effect=ForbiddenError("You do not have access to this rubric."),
            ),
            TestClient(app, raise_server_exceptions=False) as client,  # type: ignore[arg-type]
        ):
            resp = client.get(f"/api/v1/rubrics/{rubric_id}")

        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "FORBIDDEN"

    def test_returns_401_without_auth(self) -> None:
        app = create_app()
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get(f"/api/v1/rubrics/{uuid.uuid4()}")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# PATCH /api/v1/rubrics/{rubric_id}
# ---------------------------------------------------------------------------


class TestPatchRubric:
    def test_updates_rubric_name(self) -> None:
        teacher = _make_teacher()
        rubric_id = uuid.uuid4()
        updated_rubric = _make_rubric_orm(
            teacher_id=teacher.id, rubric_id=rubric_id, name="Updated"
        )
        criterion = _make_criterion_orm(rubric_id=rubric_id)
        app = _app_with_teacher(teacher)

        with (
            patch(
                "app.routers.rubrics.update_rubric",
                new_callable=AsyncMock,
                return_value=(updated_rubric, [criterion]),
            ),
            TestClient(app, raise_server_exceptions=False) as client,  # type: ignore[arg-type]
        ):
            resp = client.patch(
                f"/api/v1/rubrics/{rubric_id}",
                json={"name": "Updated"},
            )

        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["name"] == "Updated"

    def test_returns_422_for_invalid_weight_sum_in_criteria(self) -> None:
        teacher = _make_teacher()
        rubric_id = uuid.uuid4()
        app = _app_with_teacher(teacher)

        with (
            patch(
                "app.routers.rubrics.update_rubric",
                new_callable=AsyncMock,
                side_effect=RubricWeightInvalidError(
                    "Criterion weights must sum to 100. Got 50.", field="criteria"
                ),
            ),
            TestClient(app, raise_server_exceptions=False) as client,  # type: ignore[arg-type]
        ):
            resp = client.patch(
                f"/api/v1/rubrics/{rubric_id}",
                json={"criteria": [{"name": "Only", "weight": 50, "min_score": 1, "max_score": 5}]},
            )

        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "RUBRIC_WEIGHT_INVALID"

    def test_returns_403_for_cross_teacher(self) -> None:
        teacher = _make_teacher()
        rubric_id = uuid.uuid4()
        app = _app_with_teacher(teacher)

        with (
            patch(
                "app.routers.rubrics.update_rubric",
                new_callable=AsyncMock,
                side_effect=ForbiddenError("You do not have access to this rubric."),
            ),
            TestClient(app, raise_server_exceptions=False) as client,  # type: ignore[arg-type]
        ):
            resp = client.patch(f"/api/v1/rubrics/{rubric_id}", json={"name": "Hacked"})

        assert resp.status_code == 403

    def test_returns_401_without_auth(self) -> None:
        app = create_app()
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.patch(f"/api/v1/rubrics/{uuid.uuid4()}", json={"name": "X"})
        assert resp.status_code == 401

    def test_passes_description_only_when_in_fields_set(self) -> None:
        """PATCH without 'description' key must not update description."""
        teacher = _make_teacher()
        rubric_id = uuid.uuid4()
        updated_rubric = _make_rubric_orm(teacher_id=teacher.id, rubric_id=rubric_id)
        app = _app_with_teacher(teacher)

        mock_update = AsyncMock(return_value=(updated_rubric, []))
        with (
            patch("app.routers.rubrics.update_rubric", mock_update),
            TestClient(app, raise_server_exceptions=False) as client,  # type: ignore[arg-type]
        ):
            resp = client.patch(f"/api/v1/rubrics/{rubric_id}", json={"name": "New Name"})

        assert resp.status_code == 200
        call_kwargs = mock_update.call_args
        assert call_kwargs.kwargs["update_description"] is False


# ---------------------------------------------------------------------------
# DELETE /api/v1/rubrics/{rubric_id}
# ---------------------------------------------------------------------------


class TestDeleteRubric:
    def test_returns_204_on_success(self) -> None:
        teacher = _make_teacher()
        rubric_id = uuid.uuid4()
        app = _app_with_teacher(teacher)

        with (
            patch(
                "app.routers.rubrics.delete_rubric",
                new_callable=AsyncMock,
                return_value=None,
            ),
            TestClient(app, raise_server_exceptions=False) as client,  # type: ignore[arg-type]
        ):
            resp = client.delete(f"/api/v1/rubrics/{rubric_id}")

        assert resp.status_code == 204

    def test_returns_409_when_rubric_in_use(self) -> None:
        teacher = _make_teacher()
        rubric_id = uuid.uuid4()
        app = _app_with_teacher(teacher)

        with (
            patch(
                "app.routers.rubrics.delete_rubric",
                new_callable=AsyncMock,
                side_effect=RubricInUseError("Rubric is in use by one or more open assignments."),
            ),
            TestClient(app, raise_server_exceptions=False) as client,  # type: ignore[arg-type]
        ):
            resp = client.delete(f"/api/v1/rubrics/{rubric_id}")

        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "RUBRIC_IN_USE"

    def test_returns_403_for_cross_teacher(self) -> None:
        teacher = _make_teacher()
        rubric_id = uuid.uuid4()
        app = _app_with_teacher(teacher)

        with (
            patch(
                "app.routers.rubrics.delete_rubric",
                new_callable=AsyncMock,
                side_effect=ForbiddenError("You do not have access to this rubric."),
            ),
            TestClient(app, raise_server_exceptions=False) as client,  # type: ignore[arg-type]
        ):
            resp = client.delete(f"/api/v1/rubrics/{rubric_id}")

        assert resp.status_code == 403

    def test_returns_401_without_auth(self) -> None:
        app = create_app()
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.delete(f"/api/v1/rubrics/{uuid.uuid4()}")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# POST /api/v1/rubrics/{rubric_id}/duplicate
# ---------------------------------------------------------------------------


class TestDuplicateRubric:
    def test_returns_201_with_new_rubric(self) -> None:
        teacher = _make_teacher()
        source_id = uuid.uuid4()
        new_id = uuid.uuid4()
        new_rubric = _make_rubric_orm(teacher_id=teacher.id, rubric_id=new_id, name="Copy of X")
        criterion = _make_criterion_orm(rubric_id=new_id)
        app = _app_with_teacher(teacher)

        with (
            patch(
                "app.routers.rubrics.duplicate_rubric",
                new_callable=AsyncMock,
                return_value=(new_rubric, [criterion]),
            ),
            TestClient(app, raise_server_exceptions=False) as client,  # type: ignore[arg-type]
        ):
            resp = client.post(f"/api/v1/rubrics/{source_id}/duplicate")

        assert resp.status_code == 201, resp.text
        data = resp.json()["data"]
        assert data["id"] == str(new_id)
        assert data["name"] == "Copy of X"

    def test_returns_404_when_source_not_found(self) -> None:
        teacher = _make_teacher()
        app = _app_with_teacher(teacher)

        with (
            patch(
                "app.routers.rubrics.duplicate_rubric",
                new_callable=AsyncMock,
                side_effect=NotFoundError("Rubric not found."),
            ),
            TestClient(app, raise_server_exceptions=False) as client,  # type: ignore[arg-type]
        ):
            resp = client.post(f"/api/v1/rubrics/{uuid.uuid4()}/duplicate")

        assert resp.status_code == 404

    def test_returns_403_for_cross_teacher(self) -> None:
        teacher = _make_teacher()
        app = _app_with_teacher(teacher)

        with (
            patch(
                "app.routers.rubrics.duplicate_rubric",
                new_callable=AsyncMock,
                side_effect=ForbiddenError("You do not have access to this rubric."),
            ),
            TestClient(app, raise_server_exceptions=False) as client,  # type: ignore[arg-type]
        ):
            resp = client.post(f"/api/v1/rubrics/{uuid.uuid4()}/duplicate")

        assert resp.status_code == 403

    def test_returns_401_without_auth(self) -> None:
        app = create_app()
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(f"/api/v1/rubrics/{uuid.uuid4()}/duplicate")
        assert resp.status_code == 401
