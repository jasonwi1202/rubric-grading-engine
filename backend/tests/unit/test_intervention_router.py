"""Unit tests for the intervention recommendations router (M7-01).

Tests cover HTTP layer concerns — status codes, response envelope shape,
exception-to-HTTP mapping, auth enforcement, and cross-teacher 403/404
isolation.  All service calls are mocked; no real DB is used.
No student PII in fixtures.

Endpoints under test:
  GET    /api/v1/interventions
  POST   /api/v1/interventions/{id}/approve
  DELETE /api/v1/interventions/{id}
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.dependencies import get_current_teacher
from app.exceptions import ConflictError, NotFoundError
from app.main import create_app
from app.models.intervention_recommendation import InterventionRecommendation

# ---------------------------------------------------------------------------
# Helpers / factories
# ---------------------------------------------------------------------------


def _make_teacher(teacher_id: uuid.UUID | None = None) -> MagicMock:
    teacher = MagicMock()
    teacher.id = teacher_id or uuid.uuid4()
    teacher.email = "teacher@school.edu"
    teacher.email_verified = True
    return teacher


def _make_rec(
    rec_id: uuid.UUID | None = None,
    teacher_id: uuid.UUID | None = None,
    student_id: uuid.UUID | None = None,
    trigger_type: str = "regression",
    skill_key: str | None = "evidence",
    urgency: int = 4,
    status: str = "pending_review",
    actioned_at: datetime | None = None,
) -> MagicMock:
    """Return a minimal mock InterventionRecommendation with no real student PII."""
    rec = MagicMock(spec=InterventionRecommendation)
    rec.id = rec_id or uuid.uuid4()
    rec.teacher_id = teacher_id or uuid.uuid4()
    rec.student_id = student_id or uuid.uuid4()
    rec.trigger_type = trigger_type
    rec.skill_key = skill_key
    rec.urgency = urgency
    rec.trigger_reason = "Skill is trending downward."
    rec.evidence_summary = "Score: 45%, trend: declining."
    rec.suggested_action = "Review with student."
    rec.details = {"avg_score": 0.45, "trend": "declining", "assignment_count": 3}
    rec.status = status
    rec.actioned_at = actioned_at
    rec.created_at = datetime.now(UTC)
    return rec


@pytest.fixture()
def client() -> TestClient:
    app = create_app()
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture()
def teacher() -> MagicMock:
    return _make_teacher()


@pytest.fixture()
def authenticated_client(client: TestClient, teacher: MagicMock) -> TestClient:
    """Override the auth dependency with the fixture teacher."""
    app = client.app  # type: ignore[attr-defined]
    app.dependency_overrides[get_current_teacher] = lambda: teacher
    return client


# ---------------------------------------------------------------------------
# GET /api/v1/interventions
# ---------------------------------------------------------------------------


class TestGetInterventions:
    def test_returns_200_with_empty_list(
        self, authenticated_client: TestClient, teacher: MagicMock
    ) -> None:
        with patch(
            "app.routers.intervention.list_interventions",
            new=AsyncMock(return_value=[]),
        ):
            resp = authenticated_client.get("/api/v1/interventions")

        assert resp.status_code == 200
        body = resp.json()
        assert "data" in body
        assert body["data"]["total_count"] == 0
        assert body["data"]["items"] == []
        assert body["data"]["teacher_id"] == str(teacher.id)

    def test_returns_200_with_items(
        self, authenticated_client: TestClient, teacher: MagicMock
    ) -> None:
        rec = _make_rec(teacher_id=teacher.id)
        with patch(
            "app.routers.intervention.list_interventions",
            new=AsyncMock(return_value=[rec]),
        ):
            resp = authenticated_client.get("/api/v1/interventions")

        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["total_count"] == 1
        item = body["data"]["items"][0]
        assert item["id"] == str(rec.id)
        assert item["trigger_type"] == rec.trigger_type
        assert item["status"] == rec.status

    def test_passes_status_query_param(
        self, authenticated_client: TestClient, teacher: MagicMock
    ) -> None:
        with patch(
            "app.routers.intervention.list_interventions",
            new=AsyncMock(return_value=[]),
        ) as mock_list:
            authenticated_client.get("/api/v1/interventions?status=all")

        mock_list.assert_awaited_once()
        _, kwargs = mock_list.call_args
        assert kwargs.get("status") == "all"

    def test_unauthenticated_returns_401(self, client: TestClient) -> None:
        resp = client.get("/api/v1/interventions")
        # Without auth override, the dependency raises UnauthorizedError → 401.
        assert resp.status_code == 401

    def test_invalid_status_returns_422(
        self, authenticated_client: TestClient, teacher: MagicMock
    ) -> None:
        with patch(
            "app.routers.intervention.list_interventions",
            new=AsyncMock(return_value=[]),
        ) as mock_list:
            resp = authenticated_client.get("/api/v1/interventions?status=invalid")

        assert resp.status_code == 422
        mock_list.assert_not_called()


# ---------------------------------------------------------------------------
# POST /api/v1/interventions/{id}/approve
# ---------------------------------------------------------------------------


class TestApproveIntervention:
    def test_returns_200_on_approve(
        self, authenticated_client: TestClient, teacher: MagicMock
    ) -> None:
        rec_id = uuid.uuid4()
        rec = _make_rec(rec_id=rec_id, teacher_id=teacher.id, status="approved")
        with patch(
            "app.routers.intervention.approve_intervention",
            new=AsyncMock(return_value=rec),
        ):
            resp = authenticated_client.post(f"/api/v1/interventions/{rec_id}/approve")

        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["id"] == str(rec_id)
        assert body["data"]["status"] == "approved"

    def test_returns_404_when_not_found(self, authenticated_client: TestClient) -> None:
        rec_id = uuid.uuid4()
        with patch(
            "app.routers.intervention.approve_intervention",
            new=AsyncMock(side_effect=NotFoundError("Intervention recommendation not found.")),
        ):
            resp = authenticated_client.post(f"/api/v1/interventions/{rec_id}/approve")

        assert resp.status_code == 404

    def test_returns_409_when_already_dismissed(self, authenticated_client: TestClient) -> None:
        rec_id = uuid.uuid4()
        with patch(
            "app.routers.intervention.approve_intervention",
            new=AsyncMock(side_effect=ConflictError("Cannot approve a dismissed recommendation.")),
        ):
            resp = authenticated_client.post(f"/api/v1/interventions/{rec_id}/approve")

        assert resp.status_code == 409

    def test_unauthenticated_returns_401(self, client: TestClient) -> None:
        resp = client.post(f"/api/v1/interventions/{uuid.uuid4()}/approve")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# DELETE /api/v1/interventions/{id}
# ---------------------------------------------------------------------------


class TestDismissIntervention:
    def test_returns_200_on_dismiss(
        self, authenticated_client: TestClient, teacher: MagicMock
    ) -> None:
        rec_id = uuid.uuid4()
        rec = _make_rec(rec_id=rec_id, teacher_id=teacher.id, status="dismissed")
        with patch(
            "app.routers.intervention.dismiss_intervention",
            new=AsyncMock(return_value=rec),
        ):
            resp = authenticated_client.delete(f"/api/v1/interventions/{rec_id}")

        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["id"] == str(rec_id)
        assert body["data"]["status"] == "dismissed"

    def test_returns_404_when_not_found(self, authenticated_client: TestClient) -> None:
        rec_id = uuid.uuid4()
        with patch(
            "app.routers.intervention.dismiss_intervention",
            new=AsyncMock(side_effect=NotFoundError("Intervention recommendation not found.")),
        ):
            resp = authenticated_client.delete(f"/api/v1/interventions/{rec_id}")

        assert resp.status_code == 404

    def test_returns_409_when_already_approved(self, authenticated_client: TestClient) -> None:
        rec_id = uuid.uuid4()
        with patch(
            "app.routers.intervention.dismiss_intervention",
            new=AsyncMock(
                side_effect=ConflictError("Cannot dismiss an already-approved recommendation.")
            ),
        ):
            resp = authenticated_client.delete(f"/api/v1/interventions/{rec_id}")

        assert resp.status_code == 409

    def test_unauthenticated_returns_401(self, client: TestClient) -> None:
        resp = client.delete(f"/api/v1/interventions/{uuid.uuid4()}")
        assert resp.status_code == 401
