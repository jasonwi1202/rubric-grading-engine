"""Unit tests for the comment bank router endpoints.

Tests cover:
- GET  /api/v1/comment-bank                  — list, auth required
- POST /api/v1/comment-bank                  — create, auth required, validation
- DELETE /api/v1/comment-bank/{id}           — delete, 404, 403, auth required
- GET  /api/v1/comment-bank/suggestions      — suggestions, auth required

No real PostgreSQL.  All DB / service calls are mocked.  No student PII.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.dependencies import get_current_teacher
from app.exceptions import ForbiddenError, NotFoundError
from app.main import create_app
from app.models.comment_bank import CommentBankEntry

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_teacher(teacher_id: uuid.UUID | None = None) -> MagicMock:
    teacher = MagicMock()
    teacher.id = teacher_id or uuid.uuid4()
    teacher.email = "teacher@school.edu"
    teacher.email_verified = True
    return teacher


def _make_entry(
    teacher_id: uuid.UUID | None = None,
    text: str = "Good use of evidence.",
    comment_id: uuid.UUID | None = None,
) -> MagicMock:
    entry = MagicMock(spec=CommentBankEntry)
    entry.id = comment_id or uuid.uuid4()
    entry.teacher_id = teacher_id or uuid.uuid4()
    entry.text = text
    entry.created_at = datetime.now(UTC)
    return entry


def _client_with_teacher(teacher: MagicMock) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_current_teacher] = lambda: teacher
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# GET /comment-bank
# ---------------------------------------------------------------------------


class TestListComments:
    def test_returns_200_with_data_envelope(self) -> None:
        teacher = _make_teacher()
        entries = [_make_entry(teacher_id=teacher.id), _make_entry(teacher_id=teacher.id)]
        client = _client_with_teacher(teacher)

        with patch(
            "app.routers.comment_bank.list_comments",
            new_callable=AsyncMock,
            return_value=entries,
        ):
            resp = client.get("/api/v1/comment-bank")

        assert resp.status_code == 200
        body = resp.json()
        assert "data" in body
        assert len(body["data"]) == 2

    def test_returns_empty_list(self) -> None:
        teacher = _make_teacher()
        client = _client_with_teacher(teacher)

        with patch(
            "app.routers.comment_bank.list_comments",
            new_callable=AsyncMock,
            return_value=[],
        ):
            resp = client.get("/api/v1/comment-bank")

        assert resp.status_code == 200
        assert resp.json()["data"] == []

    def test_requires_auth(self) -> None:
        app = create_app()
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/api/v1/comment-bank")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# POST /comment-bank
# ---------------------------------------------------------------------------


class TestCreateComment:
    def test_returns_201_with_new_entry(self) -> None:
        teacher = _make_teacher()
        entry = _make_entry(teacher_id=teacher.id, text="Clear thesis statement.")
        client = _client_with_teacher(teacher)

        with patch(
            "app.routers.comment_bank.create_comment",
            new_callable=AsyncMock,
            return_value=entry,
        ):
            resp = client.post(
                "/api/v1/comment-bank",
                json={"text": "Clear thesis statement."},
            )

        assert resp.status_code == 201
        body = resp.json()
        assert body["data"]["text"] == "Clear thesis statement."

    def test_requires_auth(self) -> None:
        app = create_app()
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post("/api/v1/comment-bank", json={"text": "Hello"})
        assert resp.status_code == 401

    def test_rejects_empty_text(self) -> None:
        teacher = _make_teacher()
        client = _client_with_teacher(teacher)
        resp = client.post("/api/v1/comment-bank", json={"text": ""})
        assert resp.status_code == 422

    def test_rejects_missing_text(self) -> None:
        teacher = _make_teacher()
        client = _client_with_teacher(teacher)
        resp = client.post("/api/v1/comment-bank", json={})
        assert resp.status_code == 422

    def test_rejects_text_over_max_length(self) -> None:
        teacher = _make_teacher()
        client = _client_with_teacher(teacher)
        resp = client.post("/api/v1/comment-bank", json={"text": "x" * 2001})
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# DELETE /comment-bank/{id}
# ---------------------------------------------------------------------------


class TestDeleteComment:
    def test_returns_204_on_success(self) -> None:
        teacher = _make_teacher()
        comment_id = uuid.uuid4()
        client = _client_with_teacher(teacher)

        with patch(
            "app.routers.comment_bank.delete_comment",
            new_callable=AsyncMock,
            return_value=None,
        ):
            resp = client.delete(f"/api/v1/comment-bank/{comment_id}")

        assert resp.status_code == 204

    def test_returns_404_when_not_found(self) -> None:
        teacher = _make_teacher()
        comment_id = uuid.uuid4()
        client = _client_with_teacher(teacher)

        with patch(
            "app.routers.comment_bank.delete_comment",
            new_callable=AsyncMock,
            side_effect=NotFoundError("Comment not found."),
        ):
            resp = client.delete(f"/api/v1/comment-bank/{comment_id}")

        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "NOT_FOUND"

    def test_returns_403_cross_teacher(self) -> None:
        teacher = _make_teacher()
        comment_id = uuid.uuid4()
        client = _client_with_teacher(teacher)

        with patch(
            "app.routers.comment_bank.delete_comment",
            new_callable=AsyncMock,
            side_effect=ForbiddenError("You do not have access to this comment."),
        ):
            resp = client.delete(f"/api/v1/comment-bank/{comment_id}")

        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "FORBIDDEN"

    def test_requires_auth(self) -> None:
        app = create_app()
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.delete(f"/api/v1/comment-bank/{uuid.uuid4()}")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET /comment-bank/suggestions
# ---------------------------------------------------------------------------


class TestSuggestions:
    def test_returns_200_with_suggestions(self) -> None:
        teacher = _make_teacher()
        entry = _make_entry(teacher_id=teacher.id, text="Good use of evidence.")
        client = _client_with_teacher(teacher)

        with patch(
            "app.routers.comment_bank.suggest_comments",
            new_callable=AsyncMock,
            return_value=[(entry, 0.85)],
        ):
            resp = client.get("/api/v1/comment-bank/suggestions", params={"q": "evidence"})

        assert resp.status_code == 200
        body = resp.json()
        assert "data" in body
        assert len(body["data"]) == 1
        item = body["data"][0]
        assert item["text"] == "Good use of evidence."
        assert "score" in item
        assert 0.0 <= item["score"] <= 1.0

    def test_returns_empty_list_when_no_matches(self) -> None:
        teacher = _make_teacher()
        client = _client_with_teacher(teacher)

        with patch(
            "app.routers.comment_bank.suggest_comments",
            new_callable=AsyncMock,
            return_value=[],
        ):
            resp = client.get("/api/v1/comment-bank/suggestions", params={"q": "evidence"})

        assert resp.status_code == 200
        assert resp.json()["data"] == []

    def test_requires_q_param(self) -> None:
        teacher = _make_teacher()
        client = _client_with_teacher(teacher)
        resp = client.get("/api/v1/comment-bank/suggestions")
        assert resp.status_code == 422

    def test_rejects_empty_q(self) -> None:
        teacher = _make_teacher()
        client = _client_with_teacher(teacher)
        resp = client.get("/api/v1/comment-bank/suggestions", params={"q": ""})
        assert resp.status_code == 422

    def test_requires_auth(self) -> None:
        app = create_app()
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/api/v1/comment-bank/suggestions", params={"q": "evidence"})
        assert resp.status_code == 401

    @pytest.mark.parametrize("teacher_id_fixture", [None])
    def test_tenant_isolation_suggestions_scoped_to_teacher(self, teacher_id_fixture: None) -> None:
        """Suggestions endpoint passes the authenticated teacher's ID, not a client-supplied one."""
        teacher_a = _make_teacher()
        entry_a = _make_entry(teacher_id=teacher_a.id, text="Strong argument with evidence.")
        client = _client_with_teacher(teacher_a)

        captured_teacher_ids: list[uuid.UUID] = []

        async def _mock_suggest(
            db: object, teacher_id: uuid.UUID, query: str
        ) -> list[tuple[MagicMock, float]]:
            captured_teacher_ids.append(teacher_id)
            return [(entry_a, 0.9)]

        with patch("app.routers.comment_bank.suggest_comments", side_effect=_mock_suggest):
            client.get("/api/v1/comment-bank/suggestions", params={"q": "evidence"})

        assert captured_teacher_ids == [teacher_a.id]
