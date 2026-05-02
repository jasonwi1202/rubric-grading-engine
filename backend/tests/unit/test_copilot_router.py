"""Unit tests for the teacher copilot router (M7-03).

Tests cover HTTP layer concerns — status codes, response envelope shape,
exception-to-HTTP mapping, auth enforcement, and request validation.
All service calls are mocked; no real DB is used.
No student PII in fixtures.

Endpoints under test:
  POST /api/v1/copilot/query
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.dependencies import get_current_teacher
from app.exceptions import ForbiddenError, LLMError, LLMParseError, NotFoundError
from app.main import create_app
from app.schemas.copilot import CopilotQueryResponse, CopilotRankedItemResponse

# ---------------------------------------------------------------------------
# Helpers / factories
# ---------------------------------------------------------------------------


def _make_teacher(teacher_id: uuid.UUID | None = None) -> MagicMock:
    teacher = MagicMock()
    teacher.id = teacher_id or uuid.uuid4()
    teacher.email = "teacher@school.edu"
    teacher.email_verified = True
    return teacher


def _make_copilot_response(
    query_interpretation: str = "Who needs help with thesis?",
    has_sufficient_data: bool = True,
    uncertainty_note: str | None = None,
    response_type: str = "ranked_list",
    ranked_items: list[Any] | None = None,
    summary: str = "Two students need thesis support.",
    suggested_next_steps: list[str] | None = None,
    prompt_version: str = "copilot-v1",
) -> CopilotQueryResponse:
    return CopilotQueryResponse(
        query_interpretation=query_interpretation,
        has_sufficient_data=has_sufficient_data,
        uncertainty_note=uncertainty_note,
        response_type=response_type,  # type: ignore[arg-type]
        ranked_items=ranked_items or [],
        summary=summary,
        suggested_next_steps=suggested_next_steps or ["Review worklist.", "Plan mini-lesson."],
        prompt_version=prompt_version,
    )


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
# POST /api/v1/copilot/query
# ---------------------------------------------------------------------------


class TestCopilotQuery:
    def test_returns_200_with_data_envelope(
        self, authenticated_client: TestClient, teacher: MagicMock
    ) -> None:
        response = _make_copilot_response()

        with patch(
            "app.routers.copilot.execute_copilot_query",
            new=AsyncMock(return_value=response),
        ):
            resp = authenticated_client.post(
                "/api/v1/copilot/query",
                json={"query": "Who is falling behind on thesis?"},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert "data" in body
        assert body["data"]["has_sufficient_data"] is True
        assert body["data"]["response_type"] == "ranked_list"
        assert body["data"]["prompt_version"] == "copilot-v1"

    def test_returns_401_when_not_authenticated(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/copilot/query",
            json={"query": "Who needs help?"},
        )
        assert resp.status_code == 401

    def test_returns_422_when_query_missing(self, authenticated_client: TestClient) -> None:
        resp = authenticated_client.post("/api/v1/copilot/query", json={})
        assert resp.status_code == 422
        body = resp.json()
        assert "error" in body

    def test_returns_422_when_query_empty_string(self, authenticated_client: TestClient) -> None:
        resp = authenticated_client.post("/api/v1/copilot/query", json={"query": ""})
        assert resp.status_code == 422

    def test_returns_422_when_query_whitespace_only(self, authenticated_client: TestClient) -> None:
        resp = authenticated_client.post("/api/v1/copilot/query", json={"query": "   \n\t  "})
        assert resp.status_code == 422

    def test_returns_422_when_query_exceeds_500_chars(
        self, authenticated_client: TestClient
    ) -> None:
        long_query = "A" * 501
        resp = authenticated_client.post("/api/v1/copilot/query", json={"query": long_query})
        assert resp.status_code == 422

    def test_returns_404_when_class_not_found(self, authenticated_client: TestClient) -> None:
        with patch(
            "app.routers.copilot.execute_copilot_query",
            new=AsyncMock(side_effect=NotFoundError("Class not found.")),
        ):
            resp = authenticated_client.post(
                "/api/v1/copilot/query",
                json={"query": "Who is at risk?", "class_id": str(uuid.uuid4())},
            )
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "NOT_FOUND"

    def test_returns_403_when_class_belongs_to_other_teacher(
        self, authenticated_client: TestClient
    ) -> None:
        with patch(
            "app.routers.copilot.execute_copilot_query",
            new=AsyncMock(side_effect=ForbiddenError("Not your class.")),
        ):
            resp = authenticated_client.post(
                "/api/v1/copilot/query",
                json={"query": "Who is at risk?", "class_id": str(uuid.uuid4())},
            )
        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "FORBIDDEN"

    def test_returns_503_on_llm_transport_error(self, authenticated_client: TestClient) -> None:
        with patch(
            "app.routers.copilot.execute_copilot_query",
            new=AsyncMock(side_effect=LLMError("LLM unavailable.")),
        ):
            resp = authenticated_client.post(
                "/api/v1/copilot/query",
                json={"query": "What should I teach?"},
            )
        assert resp.status_code == 503

    def test_returns_500_on_llm_parse_error(self, authenticated_client: TestClient) -> None:
        with patch(
            "app.routers.copilot.execute_copilot_query",
            new=AsyncMock(side_effect=LLMParseError("Bad JSON.")),
        ):
            resp = authenticated_client.post(
                "/api/v1/copilot/query",
                json={"query": "What should I teach?"},
            )
        assert resp.status_code == 500

    def test_class_id_accepted_as_optional(self, authenticated_client: TestClient) -> None:
        class_id = uuid.uuid4()
        response = _make_copilot_response()

        with patch(
            "app.routers.copilot.execute_copilot_query",
            new=AsyncMock(return_value=response),
        ) as mock_svc:
            resp = authenticated_client.post(
                "/api/v1/copilot/query",
                json={"query": "Who is at risk?", "class_id": str(class_id)},
            )

        assert resp.status_code == 200
        call_kwargs = mock_svc.call_args.kwargs
        assert call_kwargs["class_id"] == class_id

    def test_teacher_id_from_auth_not_client(
        self, authenticated_client: TestClient, teacher: MagicMock
    ) -> None:
        """Ensures the router uses the authenticated teacher.id, not a client-supplied value."""
        response = _make_copilot_response()

        with patch(
            "app.routers.copilot.execute_copilot_query",
            new=AsyncMock(return_value=response),
        ) as mock_svc:
            authenticated_client.post(
                "/api/v1/copilot/query",
                json={"query": "Who is at risk?"},
            )

        call_kwargs = mock_svc.call_args.kwargs
        assert call_kwargs["teacher_id"] == teacher.id

    def test_uncertainty_response_forwarded(self, authenticated_client: TestClient) -> None:
        response = _make_copilot_response(
            has_sufficient_data=False,
            uncertainty_note="Too few assignments graded.",
            response_type="insufficient_data",
        )

        with patch(
            "app.routers.copilot.execute_copilot_query",
            new=AsyncMock(return_value=response),
        ):
            resp = authenticated_client.post(
                "/api/v1/copilot/query",
                json={"query": "Who is at risk?"},
            )

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["has_sufficient_data"] is False
        assert data["uncertainty_note"] == "Too few assignments graded."
        assert data["response_type"] == "insufficient_data"

    def test_ranked_items_with_student_display_name(self, authenticated_client: TestClient) -> None:
        student_id = uuid.uuid4()
        item = CopilotRankedItemResponse(
            student_id=student_id,
            student_display_name="Synthetic Learner",
            skill_dimension="thesis",
            label="Below threshold on thesis",
            value=0.42,
            explanation="avg_score=0.42, trend=stable, 4 assignments.",
        )
        response = _make_copilot_response(ranked_items=[item])

        with patch(
            "app.routers.copilot.execute_copilot_query",
            new=AsyncMock(return_value=response),
        ):
            resp = authenticated_client.post(
                "/api/v1/copilot/query",
                json={"query": "Who is falling behind on thesis?"},
            )

        assert resp.status_code == 200
        items = resp.json()["data"]["ranked_items"]
        assert len(items) == 1
        assert items[0]["student_id"] == str(student_id)
        assert items[0]["student_display_name"] == "Synthetic Learner"
        assert items[0]["skill_dimension"] == "thesis"
        assert items[0]["value"] == pytest.approx(0.42)
