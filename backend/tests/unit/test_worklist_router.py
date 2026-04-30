"""Unit tests for the worklist router endpoints (M6-05).

Tests cover HTTP layer concerns — status codes, response envelope shape,
exception-to-HTTP mapping, auth enforcement, and cross-teacher 403 isolation.
All service calls are mocked; no real DB is used.  No student PII in fixtures.

Endpoints under test:
  GET    /api/v1/worklist
  POST   /api/v1/worklist/{itemId}/complete
  POST   /api/v1/worklist/{itemId}/snooze
  DELETE /api/v1/worklist/{itemId}
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from app.dependencies import get_current_teacher
from app.exceptions import ForbiddenError, NotFoundError
from app.main import create_app
from app.models.worklist import TeacherWorklistItem

# ---------------------------------------------------------------------------
# Helpers / factories
# ---------------------------------------------------------------------------


def _make_teacher(teacher_id: uuid.UUID | None = None) -> MagicMock:
    teacher = MagicMock()
    teacher.id = teacher_id or uuid.uuid4()
    teacher.email = "teacher@school.edu"
    teacher.email_verified = True
    return teacher


def _make_worklist_item(
    item_id: uuid.UUID | None = None,
    teacher_id: uuid.UUID | None = None,
    student_id: uuid.UUID | None = None,
    trigger_type: str = "regression",
    skill_key: str | None = "evidence",
    urgency: int = 4,
    status: str = "active",
    snoozed_until: datetime | None = None,
    completed_at: datetime | None = None,
) -> MagicMock:
    """Return a minimal mock TeacherWorklistItem with no real student PII."""
    item = MagicMock(spec=TeacherWorklistItem)
    item.id = item_id or uuid.uuid4()
    item.teacher_id = teacher_id or uuid.uuid4()
    item.student_id = student_id or uuid.uuid4()
    item.trigger_type = trigger_type
    item.skill_key = skill_key
    item.urgency = urgency
    item.suggested_action = "Assign a targeted practice exercise focused on evidence."
    item.details = {"avg_score": 0.45, "trend": "stable", "in_persistent_group": False}
    item.status = status
    item.snoozed_until = snoozed_until
    item.completed_at = completed_at
    item.generated_at = datetime(2026, 4, 1, 0, 0, 0, tzinfo=UTC)
    item.created_at = datetime(2026, 4, 1, 0, 0, 0, tzinfo=UTC)
    return item


def _client(teacher: MagicMock) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_current_teacher] = lambda: teacher
    return TestClient(app, raise_server_exceptions=False)


def _anon_client() -> TestClient:
    return TestClient(create_app(), raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# GET /worklist
# ---------------------------------------------------------------------------


class TestGetWorklistEndpoint:
    def test_returns_200_with_data_envelope(self) -> None:
        teacher = _make_teacher()
        item = _make_worklist_item(teacher_id=teacher.id)
        client = _client(teacher)

        with patch(
            "app.routers.worklist.get_worklist_for_teacher",
            new_callable=AsyncMock,
            return_value=[item],
        ):
            resp = client.get("/api/v1/worklist")

        assert resp.status_code == 200
        body = resp.json()
        assert "data" in body
        assert body["data"]["teacher_id"] == str(teacher.id)
        assert body["data"]["total_count"] == 1
        assert len(body["data"]["items"]) == 1
        assert "generated_at" in body["data"]

    def test_returns_empty_worklist(self) -> None:
        teacher = _make_teacher()
        client = _client(teacher)

        with patch(
            "app.routers.worklist.get_worklist_for_teacher",
            new_callable=AsyncMock,
            return_value=[],
        ):
            resp = client.get("/api/v1/worklist")

        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["total_count"] == 0
        assert body["data"]["items"] == []

    def test_returns_multiple_items_ordered(self) -> None:
        teacher = _make_teacher()
        item1 = _make_worklist_item(teacher_id=teacher.id, urgency=4, trigger_type="regression")
        item2 = _make_worklist_item(teacher_id=teacher.id, urgency=2, trigger_type="high_inconsistency")
        client = _client(teacher)

        with patch(
            "app.routers.worklist.get_worklist_for_teacher",
            new_callable=AsyncMock,
            return_value=[item1, item2],
        ):
            resp = client.get("/api/v1/worklist")

        assert resp.status_code == 200
        items = resp.json()["data"]["items"]
        assert len(items) == 2
        assert items[0]["urgency"] == 4
        assert items[1]["urgency"] == 2

    def test_requires_auth(self) -> None:
        client = _anon_client()
        resp = client.get("/api/v1/worklist")
        assert resp.status_code == 401

    def test_teacher_id_comes_from_jwt(self) -> None:
        """get_worklist_for_teacher receives the JWT teacher_id, not a client-supplied one."""
        teacher = _make_teacher()
        client = _client(teacher)
        captured: list[uuid.UUID] = []

        async def _mock_get(db: object, teacher_id: uuid.UUID) -> list:
            captured.append(teacher_id)
            return []

        with patch("app.routers.worklist.get_worklist_for_teacher", side_effect=_mock_get):
            client.get("/api/v1/worklist")

        assert captured == [teacher.id]

    def test_item_response_shape(self) -> None:
        """Each item in the response must include the required fields."""
        teacher = _make_teacher()
        item = _make_worklist_item(teacher_id=teacher.id)
        client = _client(teacher)

        with patch(
            "app.routers.worklist.get_worklist_for_teacher",
            new_callable=AsyncMock,
            return_value=[item],
        ):
            resp = client.get("/api/v1/worklist")

        data_item = resp.json()["data"]["items"][0]
        for field in ("id", "student_id", "trigger_type", "urgency", "suggested_action", "status"):
            assert field in data_item, f"Missing field: {field}"


# ---------------------------------------------------------------------------
# POST /worklist/{itemId}/complete
# ---------------------------------------------------------------------------


class TestCompleteWorklistItemEndpoint:
    def test_returns_200_with_completed_status(self) -> None:
        teacher = _make_teacher()
        item_id = uuid.uuid4()
        item = _make_worklist_item(
            item_id=item_id,
            teacher_id=teacher.id,
            status="completed",
            completed_at=datetime(2026, 4, 2, 10, 0, 0, tzinfo=UTC),
        )
        client = _client(teacher)

        with patch(
            "app.routers.worklist.complete_worklist_item",
            new_callable=AsyncMock,
            return_value=item,
        ):
            resp = client.post(f"/api/v1/worklist/{item_id}/complete")

        assert resp.status_code == 200
        body = resp.json()
        assert "data" in body
        assert body["data"]["status"] == "completed"
        assert body["data"]["id"] == str(item_id)

    def test_requires_auth(self) -> None:
        client = _anon_client()
        resp = client.post(f"/api/v1/worklist/{uuid.uuid4()}/complete")
        assert resp.status_code == 401

    def test_returns_403_cross_teacher(self) -> None:
        teacher = _make_teacher()
        item_id = uuid.uuid4()
        client = _client(teacher)

        with patch(
            "app.routers.worklist.complete_worklist_item",
            new_callable=AsyncMock,
            side_effect=ForbiddenError("You do not have access to this worklist item."),
        ):
            resp = client.post(f"/api/v1/worklist/{item_id}/complete")

        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "FORBIDDEN"

    def test_returns_404_item_not_found(self) -> None:
        teacher = _make_teacher()
        client = _client(teacher)

        with patch(
            "app.routers.worklist.complete_worklist_item",
            new_callable=AsyncMock,
            side_effect=NotFoundError("Worklist item not found."),
        ):
            resp = client.post(f"/api/v1/worklist/{uuid.uuid4()}/complete")

        assert resp.status_code == 404

    def test_teacher_id_comes_from_jwt(self) -> None:
        teacher = _make_teacher()
        item_id = uuid.uuid4()
        item = _make_worklist_item(item_id=item_id, teacher_id=teacher.id, status="completed")
        client = _client(teacher)
        captured: list[uuid.UUID] = []

        async def _mock_complete(
            db: object, item_id: uuid.UUID, teacher_id: uuid.UUID
        ) -> MagicMock:
            captured.append(teacher_id)
            return item

        with patch("app.routers.worklist.complete_worklist_item", side_effect=_mock_complete):
            client.post(f"/api/v1/worklist/{item_id}/complete")

        assert captured == [teacher.id]


# ---------------------------------------------------------------------------
# POST /worklist/{itemId}/snooze
# ---------------------------------------------------------------------------


class TestSnoozeWorklistItemEndpoint:
    def test_returns_200_with_snoozed_status(self) -> None:
        teacher = _make_teacher()
        item_id = uuid.uuid4()
        snooze_until = datetime(2026, 5, 1, 0, 0, 0, tzinfo=UTC)
        item = _make_worklist_item(
            item_id=item_id,
            teacher_id=teacher.id,
            status="snoozed",
            snoozed_until=snooze_until,
        )
        client = _client(teacher)

        with patch(
            "app.routers.worklist.snooze_worklist_item",
            new_callable=AsyncMock,
            return_value=item,
        ):
            resp = client.post(
                f"/api/v1/worklist/{item_id}/snooze",
                json={"snoozed_until": snooze_until.isoformat()},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert "data" in body
        assert body["data"]["status"] == "snoozed"
        assert body["data"]["id"] == str(item_id)

    def test_snooze_with_no_body_uses_default(self) -> None:
        """An empty body (or omitted snoozed_until) is valid — service applies default."""
        teacher = _make_teacher()
        item_id = uuid.uuid4()
        _fixed_snooze = datetime(2026, 5, 7, 0, 0, 0, tzinfo=UTC)  # fixed 7-day deferral
        item = _make_worklist_item(
            item_id=item_id,
            teacher_id=teacher.id,
            status="snoozed",
            snoozed_until=_fixed_snooze,
        )
        client = _client(teacher)
        captured_snooze_until: list[object] = []

        async def _mock_snooze(
            db: object,
            item_id: uuid.UUID,
            teacher_id: uuid.UUID,
            snoozed_until: object = None,
        ) -> MagicMock:
            captured_snooze_until.append(snoozed_until)
            return item

        with patch("app.routers.worklist.snooze_worklist_item", side_effect=_mock_snooze):
            resp = client.post(f"/api/v1/worklist/{item_id}/snooze", json={})

        assert resp.status_code == 200
        # snoozed_until should be None (let service apply default)
        assert captured_snooze_until == [None]

    def test_snooze_with_body_omitted_entirely_uses_default(self) -> None:
        """Omitting the request body entirely (no Content-Type) must also succeed."""
        teacher = _make_teacher()
        item_id = uuid.uuid4()
        item = _make_worklist_item(item_id=item_id, teacher_id=teacher.id, status="snoozed")
        client = _client(teacher)
        captured_snooze_until: list[object] = []

        async def _mock_snooze(
            db: object,
            item_id: uuid.UUID,
            teacher_id: uuid.UUID,
            snoozed_until: object = None,
        ) -> MagicMock:
            captured_snooze_until.append(snoozed_until)
            return item

        with patch("app.routers.worklist.snooze_worklist_item", side_effect=_mock_snooze):
            # Send request with no body and no Content-Type header.
            resp = client.post(f"/api/v1/worklist/{item_id}/snooze")

        assert resp.status_code == 200
        assert captured_snooze_until == [None]

    def test_requires_auth(self) -> None:
        client = _anon_client()
        resp = client.post(f"/api/v1/worklist/{uuid.uuid4()}/snooze", json={})
        assert resp.status_code == 401

    def test_returns_403_cross_teacher(self) -> None:
        teacher = _make_teacher()
        item_id = uuid.uuid4()
        client = _client(teacher)

        with patch(
            "app.routers.worklist.snooze_worklist_item",
            new_callable=AsyncMock,
            side_effect=ForbiddenError("You do not have access to this worklist item."),
        ):
            resp = client.post(f"/api/v1/worklist/{item_id}/snooze", json={})

        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "FORBIDDEN"

    def test_returns_404_item_not_found(self) -> None:
        teacher = _make_teacher()
        client = _client(teacher)

        with patch(
            "app.routers.worklist.snooze_worklist_item",
            new_callable=AsyncMock,
            side_effect=NotFoundError("Worklist item not found."),
        ):
            resp = client.post(f"/api/v1/worklist/{uuid.uuid4()}/snooze", json={})

        assert resp.status_code == 404

    def test_teacher_id_comes_from_jwt(self) -> None:
        teacher = _make_teacher()
        item_id = uuid.uuid4()
        item = _make_worklist_item(item_id=item_id, teacher_id=teacher.id, status="snoozed")
        client = _client(teacher)
        captured: list[uuid.UUID] = []

        async def _mock_snooze(
            db: object,
            item_id: uuid.UUID,
            teacher_id: uuid.UUID,
            snoozed_until: object = None,
        ) -> MagicMock:
            captured.append(teacher_id)
            return item

        with patch("app.routers.worklist.snooze_worklist_item", side_effect=_mock_snooze):
            client.post(f"/api/v1/worklist/{item_id}/snooze", json={})

        assert captured == [teacher.id]


# ---------------------------------------------------------------------------
# DELETE /worklist/{itemId}
# ---------------------------------------------------------------------------


class TestDismissWorklistItemEndpoint:
    def test_returns_200_with_dismissed_status(self) -> None:
        teacher = _make_teacher()
        item_id = uuid.uuid4()
        item = _make_worklist_item(
            item_id=item_id,
            teacher_id=teacher.id,
            status="dismissed",
        )
        client = _client(teacher)

        with patch(
            "app.routers.worklist.dismiss_worklist_item",
            new_callable=AsyncMock,
            return_value=item,
        ):
            resp = client.delete(f"/api/v1/worklist/{item_id}")

        assert resp.status_code == 200
        body = resp.json()
        assert "data" in body
        assert body["data"]["status"] == "dismissed"
        assert body["data"]["id"] == str(item_id)

    def test_requires_auth(self) -> None:
        client = _anon_client()
        resp = client.delete(f"/api/v1/worklist/{uuid.uuid4()}")
        assert resp.status_code == 401

    def test_returns_403_cross_teacher(self) -> None:
        teacher = _make_teacher()
        item_id = uuid.uuid4()
        client = _client(teacher)

        with patch(
            "app.routers.worklist.dismiss_worklist_item",
            new_callable=AsyncMock,
            side_effect=ForbiddenError("You do not have access to this worklist item."),
        ):
            resp = client.delete(f"/api/v1/worklist/{item_id}")

        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "FORBIDDEN"

    def test_returns_404_item_not_found(self) -> None:
        teacher = _make_teacher()
        client = _client(teacher)

        with patch(
            "app.routers.worklist.dismiss_worklist_item",
            new_callable=AsyncMock,
            side_effect=NotFoundError("Worklist item not found."),
        ):
            resp = client.delete(f"/api/v1/worklist/{uuid.uuid4()}")

        assert resp.status_code == 404

    def test_teacher_id_comes_from_jwt(self) -> None:
        teacher = _make_teacher()
        item_id = uuid.uuid4()
        item = _make_worklist_item(item_id=item_id, teacher_id=teacher.id, status="dismissed")
        client = _client(teacher)
        captured: list[uuid.UUID] = []

        async def _mock_dismiss(
            db: object, item_id: uuid.UUID, teacher_id: uuid.UUID
        ) -> MagicMock:
            captured.append(teacher_id)
            return item

        with patch("app.routers.worklist.dismiss_worklist_item", side_effect=_mock_dismiss):
            client.delete(f"/api/v1/worklist/{item_id}")

        assert captured == [teacher.id]
