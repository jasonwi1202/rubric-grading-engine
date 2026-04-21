"""Unit tests for batch grading API endpoints.

Covers:
  POST /api/v1/assignments/{id}/grade          — trigger batch grading
  GET  /api/v1/assignments/{id}/grading-status — read progress
  POST /api/v1/essays/{id}/grade/retry         — retry single essay

No real PostgreSQL or Redis.  All service calls are mocked.
No student PII in any fixture.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from app.dependencies import get_current_teacher
from app.exceptions import (
    AssignmentNotGradeableError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
)
from app.main import create_app

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_teacher(teacher_id: uuid.UUID | None = None) -> MagicMock:
    teacher = MagicMock()
    teacher.id = teacher_id or uuid.uuid4()
    teacher.email_verified = True
    return teacher


def _app_with_teacher(teacher: MagicMock | None = None) -> object:
    teacher = teacher or _make_teacher()
    app = create_app()
    app.dependency_overrides[get_current_teacher] = lambda: teacher  # type: ignore[attr-defined]
    return app


def _app_with_teacher_and_redis(
    teacher: MagicMock | None = None,
    redis_mock: MagicMock | None = None,
) -> object:
    """Build an app that overrides both auth and the Redis dependency."""
    from app.routers.assignments import _get_redis as assignments_get_redis
    from app.routers.essays import _get_redis as essays_get_redis

    teacher = teacher or _make_teacher()
    redis_mock = redis_mock or MagicMock()

    app = create_app()
    app.dependency_overrides[get_current_teacher] = lambda: teacher  # type: ignore[attr-defined]
    app.dependency_overrides[assignments_get_redis] = lambda: redis_mock  # type: ignore[attr-defined]
    app.dependency_overrides[essays_get_redis] = lambda: redis_mock  # type: ignore[attr-defined]
    return app


def _default_status_data() -> dict[str, object]:
    return {
        "status": "processing",
        "total": 3,
        "complete": 1,
        "failed": 0,
        "essays": [
            {"id": str(uuid.uuid4()), "status": "complete", "student_name": None, "error": None},
        ],
    }


# ---------------------------------------------------------------------------
# POST /api/v1/assignments/{id}/grade
# ---------------------------------------------------------------------------


class TestTriggerGradingEndpoint:
    def test_returns_202_on_success(self) -> None:
        teacher = _make_teacher()
        assignment_id = uuid.uuid4()
        app = _app_with_teacher_and_redis(teacher=teacher)

        with (
            patch(
                "app.routers.assignments.trigger_batch_grading",
                new=AsyncMock(return_value=5),
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.post(
                f"/api/v1/assignments/{assignment_id}/grade",
                json={"strictness": "balanced"},
            )

        assert resp.status_code == 202, resp.text
        data = resp.json()["data"]
        assert data["enqueued"] == 5
        assert data["assignment_id"] == str(assignment_id)

    def test_returns_403_for_other_teachers_assignment(self) -> None:
        teacher = _make_teacher()
        app = _app_with_teacher_and_redis(teacher=teacher)

        with (
            patch(
                "app.routers.assignments.trigger_batch_grading",
                new=AsyncMock(side_effect=ForbiddenError("Not your assignment.")),
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.post(
                f"/api/v1/assignments/{uuid.uuid4()}/grade",
                json={},
            )

        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "FORBIDDEN"

    def test_returns_404_when_not_found(self) -> None:
        teacher = _make_teacher()
        app = _app_with_teacher_and_redis(teacher=teacher)

        with (
            patch(
                "app.routers.assignments.trigger_batch_grading",
                new=AsyncMock(side_effect=NotFoundError("Assignment not found.")),
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.post(
                f"/api/v1/assignments/{uuid.uuid4()}/grade",
                json={},
            )

        assert resp.status_code == 404

    def test_returns_409_when_not_gradeable(self) -> None:
        teacher = _make_teacher()
        app = _app_with_teacher_and_redis(teacher=teacher)

        with (
            patch(
                "app.routers.assignments.trigger_batch_grading",
                new=AsyncMock(side_effect=AssignmentNotGradeableError("No queued essays.")),
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.post(
                f"/api/v1/assignments/{uuid.uuid4()}/grade",
                json={},
            )

        assert resp.status_code == 409

    def test_returns_422_for_invalid_strictness(self) -> None:
        teacher = _make_teacher()
        app = _app_with_teacher_and_redis(teacher=teacher)

        with (
            patch("app.routers.assignments.trigger_batch_grading", new=AsyncMock()),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.post(
                f"/api/v1/assignments/{uuid.uuid4()}/grade",
                json={"strictness": "extreme"},  # not a valid value
            )

        assert resp.status_code == 422

    def test_requires_authentication(self) -> None:
        app = create_app()
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(
                f"/api/v1/assignments/{uuid.uuid4()}/grade",
                json={},
            )
        assert resp.status_code == 401

    def test_uses_authenticated_teacher_id(self) -> None:
        """The endpoint passes the authenticated teacher's id — never a client-supplied one."""
        teacher = _make_teacher()
        assignment_id = uuid.uuid4()
        app = _app_with_teacher_and_redis(teacher=teacher)
        mock_trigger = AsyncMock(return_value=1)

        with (
            patch("app.routers.assignments.trigger_batch_grading", mock_trigger),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            client.post(f"/api/v1/assignments/{assignment_id}/grade", json={})

        call_kwargs = mock_trigger.call_args.kwargs
        assert call_kwargs["teacher_id"] == teacher.id
        assert call_kwargs["assignment_id"] == assignment_id


# ---------------------------------------------------------------------------
# GET /api/v1/assignments/{id}/grading-status
# ---------------------------------------------------------------------------


class TestGetGradingStatusEndpoint:
    def test_returns_200_with_progress_data(self) -> None:
        teacher = _make_teacher()
        assignment_id = uuid.uuid4()
        app = _app_with_teacher_and_redis(teacher=teacher)

        with (
            patch(
                "app.routers.assignments.get_grading_status",
                new=AsyncMock(return_value=_default_status_data()),
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.get(f"/api/v1/assignments/{assignment_id}/grading-status")

        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["status"] == "processing"
        assert data["total"] == 3
        assert data["complete"] == 1
        assert data["failed"] == 0
        assert isinstance(data["essays"], list)

    def test_returns_idle_when_not_started(self) -> None:
        teacher = _make_teacher()
        assignment_id = uuid.uuid4()
        app = _app_with_teacher_and_redis(teacher=teacher)

        with (
            patch(
                "app.routers.assignments.get_grading_status",
                new=AsyncMock(
                    return_value={
                        "status": "idle",
                        "total": 0,
                        "complete": 0,
                        "failed": 0,
                        "essays": [],
                    }
                ),
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.get(f"/api/v1/assignments/{assignment_id}/grading-status")

        assert resp.status_code == 200
        assert resp.json()["data"]["status"] == "idle"

    def test_returns_403_for_other_teachers_assignment(self) -> None:
        teacher = _make_teacher()
        app = _app_with_teacher_and_redis(teacher=teacher)

        with (
            patch(
                "app.routers.assignments.get_grading_status",
                new=AsyncMock(side_effect=ForbiddenError("Not yours.")),
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.get(f"/api/v1/assignments/{uuid.uuid4()}/grading-status")

        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "FORBIDDEN"

    def test_returns_404_when_not_found(self) -> None:
        teacher = _make_teacher()
        app = _app_with_teacher_and_redis(teacher=teacher)

        with (
            patch(
                "app.routers.assignments.get_grading_status",
                new=AsyncMock(side_effect=NotFoundError("Not found.")),
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.get(f"/api/v1/assignments/{uuid.uuid4()}/grading-status")

        assert resp.status_code == 404

    def test_requires_authentication(self) -> None:
        app = create_app()
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get(f"/api/v1/assignments/{uuid.uuid4()}/grading-status")
        assert resp.status_code == 401

    def test_uses_authenticated_teacher_id(self) -> None:
        teacher = _make_teacher()
        assignment_id = uuid.uuid4()
        app = _app_with_teacher_and_redis(teacher=teacher)
        mock_status = AsyncMock(return_value=_default_status_data())

        with (
            patch("app.routers.assignments.get_grading_status", mock_status),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            client.get(f"/api/v1/assignments/{assignment_id}/grading-status")

        call_kwargs = mock_status.call_args.kwargs
        assert call_kwargs["teacher_id"] == teacher.id
        assert call_kwargs["assignment_id"] == assignment_id


# ---------------------------------------------------------------------------
# POST /api/v1/essays/{id}/grade/retry
# ---------------------------------------------------------------------------


class TestRetryEssayGradingEndpoint:
    def test_returns_202_on_success(self) -> None:
        teacher = _make_teacher()
        essay_id = uuid.uuid4()
        app = _app_with_teacher_and_redis(teacher=teacher)

        with (
            patch(
                "app.routers.essays.retry_essay_grading",
                new=AsyncMock(return_value=None),
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.post(f"/api/v1/essays/{essay_id}/grade/retry", json={})

        assert resp.status_code == 202, resp.text
        data = resp.json()["data"]
        assert data["essay_id"] == str(essay_id)
        assert data["status"] == "queued"

    def test_returns_403_for_other_teachers_essay(self) -> None:
        teacher = _make_teacher()
        app = _app_with_teacher_and_redis(teacher=teacher)

        with (
            patch(
                "app.routers.essays.retry_essay_grading",
                new=AsyncMock(side_effect=ForbiddenError("Not your essay.")),
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.post(f"/api/v1/essays/{uuid.uuid4()}/grade/retry", json={})

        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "FORBIDDEN"

    def test_returns_404_when_essay_not_found(self) -> None:
        teacher = _make_teacher()
        app = _app_with_teacher_and_redis(teacher=teacher)

        with (
            patch(
                "app.routers.essays.retry_essay_grading",
                new=AsyncMock(side_effect=NotFoundError("Essay not found.")),
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.post(f"/api/v1/essays/{uuid.uuid4()}/grade/retry", json={})

        assert resp.status_code == 404

    def test_returns_409_when_already_graded(self) -> None:
        teacher = _make_teacher()
        app = _app_with_teacher_and_redis(teacher=teacher)

        with (
            patch(
                "app.routers.essays.retry_essay_grading",
                new=AsyncMock(side_effect=ConflictError("Only queued essays can be retried.")),
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.post(f"/api/v1/essays/{uuid.uuid4()}/grade/retry", json={})

        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "CONFLICT"

    def test_returns_409_when_currently_grading(self) -> None:
        teacher = _make_teacher()
        app = _app_with_teacher_and_redis(teacher=teacher)

        with (
            patch(
                "app.routers.essays.retry_essay_grading",
                new=AsyncMock(side_effect=ConflictError("This essay is already being graded.")),
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.post(f"/api/v1/essays/{uuid.uuid4()}/grade/retry", json={})

        assert resp.status_code == 409

    def test_returns_422_for_invalid_strictness(self) -> None:
        teacher = _make_teacher()
        app = _app_with_teacher_and_redis(teacher=teacher)

        with (
            patch("app.routers.essays.retry_essay_grading", new=AsyncMock()),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.post(
                f"/api/v1/essays/{uuid.uuid4()}/grade/retry",
                json={"strictness": "invalid"},
            )

        assert resp.status_code == 422

    def test_requires_authentication(self) -> None:
        app = create_app()
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(f"/api/v1/essays/{uuid.uuid4()}/grade/retry", json={})
        assert resp.status_code == 401

    def test_uses_authenticated_teacher_id(self) -> None:
        teacher = _make_teacher()
        essay_id = uuid.uuid4()
        app = _app_with_teacher_and_redis(teacher=teacher)
        mock_retry = AsyncMock(return_value=None)

        with (
            patch("app.routers.essays.retry_essay_grading", mock_retry),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            client.post(f"/api/v1/essays/{essay_id}/grade/retry", json={})

        call_kwargs = mock_retry.call_args.kwargs
        assert call_kwargs["teacher_id"] == teacher.id
        assert call_kwargs["essay_id"] == essay_id
