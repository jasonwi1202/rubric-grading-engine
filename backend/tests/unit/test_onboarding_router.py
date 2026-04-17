"""Unit tests for the onboarding router endpoints.

Tests cover:
- GET /api/v1/onboarding/status -- authenticated, unauthenticated, completed/not-completed
- POST /api/v1/onboarding/complete -- marks onboarding complete, requires auth

No real student PII in fixtures.  All DB calls are mocked.
"""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.dependencies import get_current_teacher
from app.main import create_app
from app.services.auth import create_access_token


def _make_fake_teacher(
    onboarding_complete: bool = False,
    trial_ends_at: datetime | None = None,
) -> MagicMock:
    teacher = MagicMock()
    teacher.id = uuid.uuid4()
    teacher.email = "teacher@school.edu"
    teacher.first_name = "Alex"
    teacher.last_name = "Smith"
    teacher.email_verified = True
    teacher.onboarding_complete = onboarding_complete
    teacher.trial_ends_at = trial_ends_at
    return teacher


def _make_access_token(teacher_id: uuid.UUID, email: str = "teacher@school.edu") -> str:
    return create_access_token(teacher_id, email)


@pytest.fixture()
def app_with_teacher(
    request: pytest.FixtureRequest,
) -> tuple[FastAPI, MagicMock]:
    """Return a FastAPI app with get_current_teacher overridden to a fake teacher."""
    teacher = request.param if hasattr(request, "param") else _make_fake_teacher()
    application = create_app()
    application.dependency_overrides[get_current_teacher] = lambda: teacher
    return application, teacher


# ---------------------------------------------------------------------------
# GET /api/v1/onboarding/status
# ---------------------------------------------------------------------------


class TestGetOnboardingStatus:
    def test_returns_step_1_not_complete(self) -> None:
        teacher = _make_fake_teacher(onboarding_complete=False)
        app = create_app()
        app.dependency_overrides[get_current_teacher] = lambda: teacher

        with patch(
            "app.routers.onboarding.get_onboarding_status",
            new_callable=AsyncMock,
            return_value=(1, False),
        ):
            with TestClient(app, raise_server_exceptions=False) as client:
                resp = client.get("/api/v1/onboarding/status")

        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["step"] == 1
        assert data["completed"] is False

    def test_returns_step_2_complete(self) -> None:
        trial_end = datetime.now(UTC) + timedelta(days=30)
        teacher = _make_fake_teacher(onboarding_complete=True, trial_ends_at=trial_end)
        app = create_app()
        app.dependency_overrides[get_current_teacher] = lambda: teacher

        with patch(
            "app.routers.onboarding.get_onboarding_status",
            new_callable=AsyncMock,
            return_value=(2, True),
        ):
            with TestClient(app, raise_server_exceptions=False) as client:
                resp = client.get("/api/v1/onboarding/status")

        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["step"] == 2
        assert data["completed"] is True
        assert data["trial_ends_at"] is not None

    def test_returns_403_without_auth(self) -> None:
        app = create_app()
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/api/v1/onboarding/status")
        # Missing auth header triggers 403 (FORBIDDEN) from HTTPBearer(auto_error=False)
        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "FORBIDDEN"

    def test_trial_ends_at_null_when_not_set(self) -> None:
        teacher = _make_fake_teacher(onboarding_complete=False, trial_ends_at=None)
        app = create_app()
        app.dependency_overrides[get_current_teacher] = lambda: teacher

        with patch(
            "app.routers.onboarding.get_onboarding_status",
            new_callable=AsyncMock,
            return_value=(1, False),
        ):
            with TestClient(app, raise_server_exceptions=False) as client:
                resp = client.get("/api/v1/onboarding/status")

        assert resp.status_code == 200
        assert resp.json()["data"]["trial_ends_at"] is None


# ---------------------------------------------------------------------------
# POST /api/v1/onboarding/complete
# ---------------------------------------------------------------------------


class TestMarkOnboardingComplete:
    def test_marks_complete_and_returns_message(self) -> None:
        teacher = _make_fake_teacher(onboarding_complete=False)
        updated_teacher = _make_fake_teacher(onboarding_complete=True)
        app = create_app()
        app.dependency_overrides[get_current_teacher] = lambda: teacher

        with patch(
            "app.routers.onboarding.complete_onboarding",
            new_callable=AsyncMock,
            return_value=updated_teacher,
        ):
            with TestClient(app, raise_server_exceptions=False) as client:
                resp = client.post("/api/v1/onboarding/complete")

        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert "message" in data
        assert "complete" in data["message"].lower()

    def test_returns_403_without_auth(self) -> None:
        app = create_app()
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post("/api/v1/onboarding/complete")
        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "FORBIDDEN"

    def test_idempotent_when_already_complete(self) -> None:
        """Calling complete again when already complete should still return 200."""
        teacher = _make_fake_teacher(onboarding_complete=True)
        app = create_app()
        app.dependency_overrides[get_current_teacher] = lambda: teacher

        with patch(
            "app.routers.onboarding.complete_onboarding",
            new_callable=AsyncMock,
            return_value=teacher,
        ):
            with TestClient(app, raise_server_exceptions=False) as client:
                resp = client.post("/api/v1/onboarding/complete")

        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Cross-tenant: wrong teacher cannot access another's data
# ---------------------------------------------------------------------------


class TestOnboardingTenantIsolation:
    def test_status_uses_authenticated_teacher_id(self) -> None:
        """The status endpoint uses the teacher from the JWT, not a query param."""
        teacher_a = _make_fake_teacher()
        app = create_app()
        app.dependency_overrides[get_current_teacher] = lambda: teacher_a

        with patch(
            "app.routers.onboarding.get_onboarding_status",
            new_callable=AsyncMock,
            return_value=(1, False),
        ) as mock_status:
            with TestClient(app, raise_server_exceptions=False) as client:
                resp = client.get("/api/v1/onboarding/status")

        assert resp.status_code == 200
        # Verify it was called with Teacher A's ID, not some other teacher
        mock_status.assert_called_once()
        call_teacher_id = mock_status.call_args[0][1]
        assert call_teacher_id == teacher_a.id
