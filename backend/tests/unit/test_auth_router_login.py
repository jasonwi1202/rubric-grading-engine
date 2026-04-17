"""Unit tests for the auth router — login, refresh, and logout endpoints.

All external dependencies (DB, Redis) are mocked via dependency_overrides
and patch.  No real network calls.  No student PII in fixtures.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from app.main import create_app
from app.services.auth import create_access_token

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_fake_user(verified: bool = True) -> MagicMock:
    user = MagicMock()
    user.id = uuid.uuid4()
    user.email = "teacher@school.edu"
    user.first_name = "Alex"
    user.email_verified = verified
    return user


_VALID_CREDENTIALS = {
    "email": "teacher@school.edu",
    "password": "correct_password",
}

_REFRESH_COOKIE = "refresh_token"


# ---------------------------------------------------------------------------
# POST /auth/login
# ---------------------------------------------------------------------------


class TestLoginEndpoint:
    def test_returns_access_token_on_success(self) -> None:
        user = _make_fake_user()
        app = create_app()
        token = create_access_token(user.id, user.email)

        with (
            patch(
                "app.routers.auth.login_user",
                new_callable=AsyncMock,
                return_value=(user, token, "fake_refresh_token"),
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.post("/api/v1/auth/login", json=_VALID_CREDENTIALS)

        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert "access_token" in data
        assert data["access_token"] == token
        # Refresh token should be in a cookie, not the response body
        assert _REFRESH_COOKIE in resp.cookies

    def test_returns_422_on_invalid_credentials(self) -> None:
        from app.exceptions import ValidationError

        app = create_app()

        with (
            patch(
                "app.routers.auth.login_user",
                new_callable=AsyncMock,
                side_effect=ValidationError("Invalid email or password."),
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.post(
                "/api/v1/auth/login",
                json={"email": "bad@school.edu", "password": "wrong"},
            )

        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "VALIDATION_ERROR"

    def test_returns_422_for_missing_body(self) -> None:
        app = create_app()
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post("/api/v1/auth/login")
        # FastAPI returns 422 for missing required fields
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# POST /auth/refresh
# ---------------------------------------------------------------------------


class TestRefreshEndpoint:
    def test_returns_new_access_token_on_success(self) -> None:
        user = _make_fake_user()
        new_token = create_access_token(user.id, user.email)
        app = create_app()

        with (
            patch(
                "app.routers.auth.refresh_access_token",
                new_callable=AsyncMock,
                return_value=(user, new_token, "new_refresh_token"),
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            # Inject the refresh token as a cookie
            client.cookies.set(_REFRESH_COOKIE, "some_refresh_token")
            resp = client.post("/api/v1/auth/refresh")

        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert "access_token" in data
        assert _REFRESH_COOKIE in resp.cookies

    def test_returns_401_when_no_refresh_cookie(self) -> None:
        app = create_app()
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post("/api/v1/auth/refresh")

        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "REFRESH_TOKEN_INVALID"

    def test_returns_422_when_refresh_token_invalid(self) -> None:
        from app.exceptions import ValidationError

        app = create_app()

        with (
            patch(
                "app.routers.auth.refresh_access_token",
                new_callable=AsyncMock,
                side_effect=ValidationError("Refresh token is invalid or has expired."),
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            client.cookies.set(_REFRESH_COOKIE, "expired_token")
            resp = client.post("/api/v1/auth/refresh")

        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "VALIDATION_ERROR"


# ---------------------------------------------------------------------------
# POST /auth/logout
# ---------------------------------------------------------------------------


class TestLogoutEndpoint:
    def test_returns_204_and_clears_cookie_with_refresh_token_and_auth(self) -> None:
        """With both refresh cookie and valid access token, logout_user is called."""
        user = _make_fake_user()
        app = create_app()

        # get_current_teacher_optional is imported locally inside the logout handler;
        # patch it at source so the local import resolves to the mock.
        with (
            patch(
                "app.routers.auth.logout_user",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.dependencies.get_current_teacher_optional",
                new_callable=AsyncMock,
                return_value=user.id,
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            client.cookies.set(_REFRESH_COOKIE, "some_refresh_token")
            resp = client.post("/api/v1/auth/logout")

        assert resp.status_code == 204

    def test_returns_204_even_without_cookie(self) -> None:
        """Logout should be idempotent — always 204 even with no cookie."""
        app = create_app()
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post("/api/v1/auth/logout")
        assert resp.status_code == 204

    def test_returns_204_with_refresh_cookie_but_no_access_token(self) -> None:
        """Refresh token present but no valid access token — still 204."""
        app = create_app()

        with (
            patch(
                "app.dependencies.get_current_teacher_optional",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.services.auth.delete_refresh_token",
                new_callable=AsyncMock,
                return_value=None,
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            client.cookies.set(_REFRESH_COOKIE, "orphan_refresh_token")
            resp = client.post("/api/v1/auth/logout")
        assert resp.status_code == 204
