"""Unit tests for the regrade request router endpoints.

Tests cover HTTP layer concerns — status codes, response envelope shape,
exception-to-HTTP mapping, auth enforcement, and cross-tenant 403 isolation.
All service calls are mocked; no real DB is used.  No student PII in fixtures.

Endpoints under test:
  POST /api/v1/grades/{gradeId}/regrade-requests
  GET  /api/v1/assignments/{assignmentId}/regrade-requests
  POST /api/v1/regrade-requests/{requestId}/resolve
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.dependencies import get_current_teacher
from app.exceptions import (
    ConflictError,
    ForbiddenError,
    GradeLockedError,
    NotFoundError,
    RegradeRequestLimitReachedError,
    RegradeWindowClosedError,
)
from app.main import create_app
from app.models.regrade_request import RegradeRequestStatus
from app.schemas.regrade_request import RegradeRequestResponse

# ---------------------------------------------------------------------------
# Helpers / factories
# ---------------------------------------------------------------------------


def _make_teacher(teacher_id: uuid.UUID | None = None) -> MagicMock:
    teacher = MagicMock()
    teacher.id = teacher_id or uuid.uuid4()
    teacher.email = "teacher@school.edu"
    teacher.email_verified = True
    return teacher


def _make_response(
    grade_id: uuid.UUID | None = None,
    teacher_id: uuid.UUID | None = None,
    request_id: uuid.UUID | None = None,
) -> RegradeRequestResponse:
    return RegradeRequestResponse(
        id=request_id or uuid.uuid4(),
        grade_id=grade_id or uuid.uuid4(),
        criterion_score_id=None,
        teacher_id=teacher_id or uuid.uuid4(),
        dispute_text="Score seems low.",
        status=RegradeRequestStatus.open,
        resolution_note=None,
        resolved_at=None,
        created_at=datetime.now(UTC),
    )


def _client(teacher: MagicMock) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_current_teacher] = lambda: teacher
    return TestClient(app, raise_server_exceptions=False)


def _anon_client() -> TestClient:
    return TestClient(create_app(), raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# POST /grades/{gradeId}/regrade-requests
# ---------------------------------------------------------------------------


class TestCreateRegradeRequestEndpoint:
    def test_returns_201_with_data_envelope(self) -> None:
        teacher = _make_teacher()
        grade_id = uuid.uuid4()
        rr_response = _make_response(grade_id=grade_id, teacher_id=teacher.id)
        client = _client(teacher)

        with patch(
            "app.routers.regrade_requests.create_regrade_request",
            new_callable=AsyncMock,
            return_value=rr_response,
        ):
            resp = client.post(
                f"/api/v1/grades/{grade_id}/regrade-requests",
                json={"dispute_text": "Score seems low."},
            )

        assert resp.status_code == 201
        body = resp.json()
        assert "data" in body
        assert body["data"]["grade_id"] == str(grade_id)
        assert body["data"]["status"] == "open"

    def test_requires_auth(self) -> None:
        client = _anon_client()
        resp = client.post(
            f"/api/v1/grades/{uuid.uuid4()}/regrade-requests",
            json={"dispute_text": "Score seems low."},
        )
        assert resp.status_code == 401

    def test_returns_403_cross_teacher(self) -> None:
        teacher = _make_teacher()
        grade_id = uuid.uuid4()
        client = _client(teacher)

        with patch(
            "app.routers.regrade_requests.create_regrade_request",
            new_callable=AsyncMock,
            side_effect=ForbiddenError("You do not have access to this grade."),
        ):
            resp = client.post(
                f"/api/v1/grades/{grade_id}/regrade-requests",
                json={"dispute_text": "Score seems low."},
            )

        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "FORBIDDEN"

    def test_returns_404_grade_not_found(self) -> None:
        teacher = _make_teacher()
        client = _client(teacher)

        with patch(
            "app.routers.regrade_requests.create_regrade_request",
            new_callable=AsyncMock,
            side_effect=NotFoundError("Grade not found."),
        ):
            resp = client.post(
                f"/api/v1/grades/{uuid.uuid4()}/regrade-requests",
                json={"dispute_text": "Score seems low."},
            )

        assert resp.status_code == 404

    def test_returns_409_window_closed(self) -> None:
        teacher = _make_teacher()
        client = _client(teacher)

        with patch(
            "app.routers.regrade_requests.create_regrade_request",
            new_callable=AsyncMock,
            side_effect=RegradeWindowClosedError("Window has closed."),
        ):
            resp = client.post(
                f"/api/v1/grades/{uuid.uuid4()}/regrade-requests",
                json={"dispute_text": "Score seems low."},
            )

        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "REGRADE_WINDOW_CLOSED"

    def test_returns_409_limit_reached(self) -> None:
        teacher = _make_teacher()
        client = _client(teacher)

        with patch(
            "app.routers.regrade_requests.create_regrade_request",
            new_callable=AsyncMock,
            side_effect=RegradeRequestLimitReachedError("Limit reached."),
        ):
            resp = client.post(
                f"/api/v1/grades/{uuid.uuid4()}/regrade-requests",
                json={"dispute_text": "Score seems low."},
            )

        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "REGRADE_REQUEST_LIMIT_REACHED"

    def test_rejects_empty_dispute_text(self) -> None:
        teacher = _make_teacher()
        client = _client(teacher)
        resp = client.post(
            f"/api/v1/grades/{uuid.uuid4()}/regrade-requests",
            json={"dispute_text": ""},
        )
        assert resp.status_code == 422

    def test_teacher_id_comes_from_jwt_not_body(self) -> None:
        """Service receives the JWT teacher_id, not any client-supplied value."""
        teacher = _make_teacher()
        grade_id = uuid.uuid4()
        rr_response = _make_response(grade_id=grade_id, teacher_id=teacher.id)
        client = _client(teacher)
        captured: list[uuid.UUID] = []

        async def _mock_create(
            db: object, grade_id: uuid.UUID, teacher_id: uuid.UUID, body: object
        ) -> RegradeRequestResponse:
            captured.append(teacher_id)
            return rr_response

        with patch("app.routers.regrade_requests.create_regrade_request", side_effect=_mock_create):
            client.post(
                f"/api/v1/grades/{grade_id}/regrade-requests",
                json={"dispute_text": "Score seems low."},
            )

        assert captured == [teacher.id]


# ---------------------------------------------------------------------------
# GET /assignments/{assignmentId}/regrade-requests
# ---------------------------------------------------------------------------


class TestListRegradeRequestsEndpoint:
    def test_returns_200_with_data_list(self) -> None:
        teacher = _make_teacher()
        assignment_id = uuid.uuid4()
        rr1 = _make_response(teacher_id=teacher.id)
        rr2 = _make_response(teacher_id=teacher.id)
        client = _client(teacher)

        with patch(
            "app.routers.regrade_requests.list_regrade_requests_for_assignment",
            new_callable=AsyncMock,
            return_value=[rr1, rr2],
        ):
            resp = client.get(f"/api/v1/assignments/{assignment_id}/regrade-requests")

        assert resp.status_code == 200
        body = resp.json()
        assert "data" in body
        assert len(body["data"]) == 2

    def test_returns_empty_list(self) -> None:
        teacher = _make_teacher()
        assignment_id = uuid.uuid4()
        client = _client(teacher)

        with patch(
            "app.routers.regrade_requests.list_regrade_requests_for_assignment",
            new_callable=AsyncMock,
            return_value=[],
        ):
            resp = client.get(f"/api/v1/assignments/{assignment_id}/regrade-requests")

        assert resp.status_code == 200
        assert resp.json()["data"] == []

    def test_requires_auth(self) -> None:
        client = _anon_client()
        resp = client.get(f"/api/v1/assignments/{uuid.uuid4()}/regrade-requests")
        assert resp.status_code == 401

    def test_returns_403_cross_teacher(self) -> None:
        teacher = _make_teacher()
        assignment_id = uuid.uuid4()
        client = _client(teacher)

        with patch(
            "app.routers.regrade_requests.list_regrade_requests_for_assignment",
            new_callable=AsyncMock,
            side_effect=ForbiddenError("You do not have access to this assignment."),
        ):
            resp = client.get(f"/api/v1/assignments/{assignment_id}/regrade-requests")

        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "FORBIDDEN"

    def test_returns_404_assignment_not_found(self) -> None:
        teacher = _make_teacher()
        client = _client(teacher)

        with patch(
            "app.routers.regrade_requests.list_regrade_requests_for_assignment",
            new_callable=AsyncMock,
            side_effect=NotFoundError("Assignment not found."),
        ):
            resp = client.get(f"/api/v1/assignments/{uuid.uuid4()}/regrade-requests")

        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /regrade-requests/{requestId}/resolve
# ---------------------------------------------------------------------------


class TestResolveRegradeRequestEndpoint:
    def test_returns_200_approve_with_data_envelope(self) -> None:
        teacher = _make_teacher()
        request_id = uuid.uuid4()
        rr_response = _make_response(teacher_id=teacher.id, request_id=request_id)
        # Simulate the approved state that the service would return.
        rr_response = RegradeRequestResponse(
            **{
                **rr_response.model_dump(),
                "status": RegradeRequestStatus.approved,
                "resolution_note": "Well argued.",
                "resolved_at": datetime.now(UTC),
            }
        )
        client = _client(teacher)

        with patch(
            "app.routers.regrade_requests.resolve_regrade_request",
            new_callable=AsyncMock,
            return_value=rr_response,
        ):
            resp = client.post(
                f"/api/v1/regrade-requests/{request_id}/resolve",
                json={"resolution": "approved", "resolution_note": "Well argued."},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert "data" in body
        assert body["data"]["status"] == "approved"

    def test_returns_200_deny(self) -> None:
        teacher = _make_teacher()
        request_id = uuid.uuid4()
        rr_response = _make_response(teacher_id=teacher.id, request_id=request_id)
        rr_response = RegradeRequestResponse(
            **{
                **rr_response.model_dump(),
                "status": RegradeRequestStatus.denied,
                "resolution_note": "Original score is correct.",
                "resolved_at": datetime.now(UTC),
            }
        )
        client = _client(teacher)

        with patch(
            "app.routers.regrade_requests.resolve_regrade_request",
            new_callable=AsyncMock,
            return_value=rr_response,
        ):
            resp = client.post(
                f"/api/v1/regrade-requests/{request_id}/resolve",
                json={
                    "resolution": "denied",
                    "resolution_note": "Original score is correct.",
                },
            )

        assert resp.status_code == 200
        assert resp.json()["data"]["status"] == "denied"

    def test_requires_auth(self) -> None:
        client = _anon_client()
        resp = client.post(
            f"/api/v1/regrade-requests/{uuid.uuid4()}/resolve",
            json={"resolution": "approved"},
        )
        assert resp.status_code == 401

    def test_returns_403_cross_teacher(self) -> None:
        teacher = _make_teacher()
        request_id = uuid.uuid4()
        client = _client(teacher)

        with patch(
            "app.routers.regrade_requests.resolve_regrade_request",
            new_callable=AsyncMock,
            side_effect=ForbiddenError("You do not have access to this regrade request."),
        ):
            resp = client.post(
                f"/api/v1/regrade-requests/{request_id}/resolve",
                json={"resolution": "approved"},
            )

        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "FORBIDDEN"

    def test_returns_404_request_not_found(self) -> None:
        teacher = _make_teacher()
        client = _client(teacher)

        with patch(
            "app.routers.regrade_requests.resolve_regrade_request",
            new_callable=AsyncMock,
            side_effect=NotFoundError("Regrade request not found."),
        ):
            resp = client.post(
                f"/api/v1/regrade-requests/{uuid.uuid4()}/resolve",
                json={"resolution": "approved"},
            )

        assert resp.status_code == 404

    def test_returns_409_already_resolved(self) -> None:
        teacher = _make_teacher()
        client = _client(teacher)

        with patch(
            "app.routers.regrade_requests.resolve_regrade_request",
            new_callable=AsyncMock,
            side_effect=ConflictError("This regrade request has already been resolved."),
        ):
            resp = client.post(
                f"/api/v1/regrade-requests/{uuid.uuid4()}/resolve",
                json={"resolution": "approved"},
            )

        assert resp.status_code == 409

    def test_returns_409_grade_locked(self) -> None:
        teacher = _make_teacher()
        client = _client(teacher)

        with patch(
            "app.routers.regrade_requests.resolve_regrade_request",
            new_callable=AsyncMock,
            side_effect=GradeLockedError("Grade is locked and cannot be edited."),
        ):
            resp = client.post(
                f"/api/v1/regrade-requests/{uuid.uuid4()}/resolve",
                json={"resolution": "approved", "new_criterion_score": 5},
            )

        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "GRADE_LOCKED"

    def test_rejects_invalid_resolution_value(self) -> None:
        teacher = _make_teacher()
        client = _client(teacher)
        resp = client.post(
            f"/api/v1/regrade-requests/{uuid.uuid4()}/resolve",
            json={"resolution": "maybe"},
        )
        assert resp.status_code == 422

    @pytest.mark.parametrize("resolution", ["approved", "denied"])
    def test_teacher_id_comes_from_jwt_not_body(self, resolution: str) -> None:
        """Service receives the JWT teacher_id for both approve and deny paths."""
        teacher = _make_teacher()
        request_id = uuid.uuid4()
        rr_response = _make_response(teacher_id=teacher.id, request_id=request_id)
        client = _client(teacher)
        captured: list[uuid.UUID] = []

        async def _mock_resolve(
            db: object,
            request_id: uuid.UUID,
            teacher_id: uuid.UUID,
            body: object,
        ) -> RegradeRequestResponse:
            captured.append(teacher_id)
            return rr_response

        payload: dict[str, object] = {"resolution": resolution}
        if resolution == "denied":
            payload["resolution_note"] = "Rubric score is correct."

        with patch(
            "app.routers.regrade_requests.resolve_regrade_request",
            side_effect=_mock_resolve,
        ):
            client.post(
                f"/api/v1/regrade-requests/{request_id}/resolve",
                json=payload,
            )

        assert captured == [teacher.id]
