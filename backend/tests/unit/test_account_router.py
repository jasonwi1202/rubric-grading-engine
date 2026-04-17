"""Unit tests for the account router endpoints.

Tests cover:
- GET /api/v1/account/trial — happy path (active trial, expired trial, no trial),
  unauthenticated request, response envelope shape.

No real student PII in fixtures.  All DB calls are mocked via
``dependency_overrides``.
"""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from app.dependencies import get_current_teacher
from app.main import create_app


def _make_fake_teacher(trial_ends_at: datetime | None = None) -> MagicMock:
    """Return a minimal mock User with no PII."""
    teacher = MagicMock()
    teacher.id = uuid.uuid4()
    teacher.email = "teacher@school.edu"
    teacher.email_verified = True
    teacher.trial_ends_at = trial_ends_at
    return teacher


# ---------------------------------------------------------------------------
# GET /api/v1/account/trial — happy path
# ---------------------------------------------------------------------------


class TestGetTrialStatusHappyPath:
    def test_returns_200(self) -> None:
        teacher = _make_fake_teacher(
            trial_ends_at=datetime.now(UTC) + timedelta(days=10)
        )
        app = create_app()
        app.dependency_overrides[get_current_teacher] = lambda: teacher

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/api/v1/account/trial")

        assert resp.status_code == 200, resp.text

    def test_response_contains_data_envelope(self) -> None:
        teacher = _make_fake_teacher(
            trial_ends_at=datetime.now(UTC) + timedelta(days=10)
        )
        app = create_app()
        app.dependency_overrides[get_current_teacher] = lambda: teacher

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/api/v1/account/trial")

        body = resp.json()
        assert "data" in body, f"Missing 'data' envelope: {body}"
        data = body["data"]
        assert "trial_ends_at" in data
        assert "is_active" in data
        assert "days_remaining" in data

    def test_active_trial_returns_is_active_true(self) -> None:
        teacher = _make_fake_teacher(
            trial_ends_at=datetime.now(UTC) + timedelta(days=5)
        )
        app = create_app()
        app.dependency_overrides[get_current_teacher] = lambda: teacher

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/api/v1/account/trial")

        data = resp.json()["data"]
        assert data["is_active"] is True, f"Expected is_active=True: {data}"
        assert isinstance(data["days_remaining"], int)
        assert data["days_remaining"] >= 0

    def test_expired_trial_returns_is_active_false(self) -> None:
        teacher = _make_fake_teacher(
            trial_ends_at=datetime.now(UTC) - timedelta(days=1)
        )
        app = create_app()
        app.dependency_overrides[get_current_teacher] = lambda: teacher

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/api/v1/account/trial")

        data = resp.json()["data"]
        assert data["is_active"] is False, f"Expected is_active=False: {data}"
        assert isinstance(data["days_remaining"], int)
        assert data["days_remaining"] < 0

    def test_no_trial_end_date_returns_null_days_remaining(self) -> None:
        teacher = _make_fake_teacher(trial_ends_at=None)
        app = create_app()
        app.dependency_overrides[get_current_teacher] = lambda: teacher

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/api/v1/account/trial")

        data = resp.json()["data"]
        assert data["trial_ends_at"] is None
        assert data["days_remaining"] is None
        assert data["is_active"] is True


# ---------------------------------------------------------------------------
# GET /api/v1/account/trial — authentication errors
# ---------------------------------------------------------------------------


class TestGetTrialStatusAuth:
    def test_returns_401_when_no_token(self) -> None:
        """Requests without a Bearer token must receive a 401."""
        app = create_app()

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/api/v1/account/trial")

        assert resp.status_code == 401, f"Expected 401, got {resp.status_code}: {resp.text}"

    def test_returns_401_with_invalid_token(self) -> None:
        """Requests with a malformed Bearer token must receive a 401."""
        app = create_app()

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get(
                "/api/v1/account/trial",
                headers={"Authorization": "Bearer not-a-valid-jwt"},
            )

        assert resp.status_code == 401, f"Expected 401, got {resp.status_code}: {resp.text}"
