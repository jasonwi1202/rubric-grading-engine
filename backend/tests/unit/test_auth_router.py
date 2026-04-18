"""Unit tests for the auth router endpoints.

Tests cover:
- POST /api/v1/auth/signup — happy path, duplicate email, rate limit,
  validation failures
- GET  /api/v1/auth/verify-email — valid token, invalid/expired token
- POST /api/v1/auth/resend-verification — always 202

No real student PII in fixtures.  All DB/Redis/Celery calls are mocked.
"""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app(), raise_server_exceptions=False)


def _make_signup_payload(**overrides: object) -> dict:
    base: dict = {
        "email": "teacher@school.edu",
        "password": "Password1",
        "first_name": "Alex",
        "last_name": "Smith",
        "school_name": "Test High School",
    }
    base.update(overrides)
    return base


def _make_fake_user(email: str = "teacher@school.edu") -> MagicMock:
    user = MagicMock()
    user.id = uuid.uuid4()
    user.email = email
    user.first_name = "Alex"
    user.last_name = "Smith"
    user.school_name = "Test High School"
    user.email_verified = False
    user.created_at = datetime.now(UTC)
    return user


# ---------------------------------------------------------------------------
# POST /api/v1/auth/signup — happy path
# ---------------------------------------------------------------------------


class TestSignupHappyPath:
    def test_returns_201(self, client: TestClient) -> None:
        fake_user = _make_fake_user()

        with (
            patch(
                "app.routers.auth.create_user",
                new_callable=AsyncMock,
                return_value=fake_user,
            ),
            patch(
                "app.routers.auth.generate_verification_token",
                return_value=("raw_token", "hmac_tag"),
            ),
            patch("app.routers.auth.store_verification_token", new_callable=AsyncMock),
            patch("app.routers.auth._get_redis"),
            patch("app.tasks.email.send_verification_email.delay"),
        ):
            resp = client.post("/api/v1/auth/signup", json=_make_signup_payload())

        assert resp.status_code == 201, f"Got {resp.status_code}: {resp.text}"

    def test_returns_data_envelope_with_user_id(self, client: TestClient) -> None:
        fake_user = _make_fake_user()

        with (
            patch(
                "app.routers.auth.create_user",
                new_callable=AsyncMock,
                return_value=fake_user,
            ),
            patch(
                "app.routers.auth.generate_verification_token",
                return_value=("raw_token", "hmac_tag"),
            ),
            patch("app.routers.auth.store_verification_token", new_callable=AsyncMock),
            patch("app.routers.auth._get_redis"),
            patch("app.tasks.email.send_verification_email.delay"),
        ):
            resp = client.post("/api/v1/auth/signup", json=_make_signup_payload())

        body = resp.json()
        assert "data" in body, f"Missing 'data' key: {body}"
        assert body["data"]["id"] == str(fake_user.id)
        assert body["data"]["email"] == fake_user.email

    def test_verification_email_task_is_enqueued(self, client: TestClient) -> None:
        fake_user = _make_fake_user()

        with (
            patch(
                "app.routers.auth.create_user",
                new_callable=AsyncMock,
                return_value=fake_user,
            ),
            patch(
                "app.routers.auth.generate_verification_token",
                return_value=("raw_token", "hmac_tag"),
            ),
            patch("app.routers.auth.store_verification_token", new_callable=AsyncMock),
            patch("app.routers.auth._get_redis"),
            patch("app.tasks.email.send_verification_email.delay") as mock_delay,
        ):
            client.post("/api/v1/auth/signup", json=_make_signup_payload())

        mock_delay.assert_called_once_with(
            user_id=str(fake_user.id),
            raw_token="raw_token",
        )


# ---------------------------------------------------------------------------
# POST /api/v1/auth/signup — validation errors
# ---------------------------------------------------------------------------


class TestSignupValidation:
    def test_missing_email_returns_422(self, client: TestClient) -> None:
        payload = _make_signup_payload()
        del payload["email"]
        resp = client.post("/api/v1/auth/signup", json=payload)
        assert resp.status_code == 422

    def test_invalid_email_returns_422(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/auth/signup",
            json=_make_signup_payload(email="not-an-email"),
        )
        assert resp.status_code == 422

    def test_missing_password_returns_422(self, client: TestClient) -> None:
        payload = _make_signup_payload()
        del payload["password"]
        resp = client.post("/api/v1/auth/signup", json=payload)
        assert resp.status_code == 422

    def test_short_password_returns_422(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/auth/signup",
            json=_make_signup_payload(password="Ab1"),
        )
        assert resp.status_code == 422

    def test_password_without_digit_returns_422(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/auth/signup",
            json=_make_signup_payload(password="OnlyLetters"),
        )
        assert resp.status_code == 422

    def test_password_without_letter_returns_422(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/auth/signup",
            json=_make_signup_payload(password="12345678"),
        )
        assert resp.status_code == 422

    def test_missing_first_name_returns_422(self, client: TestClient) -> None:
        payload = _make_signup_payload()
        del payload["first_name"]
        resp = client.post("/api/v1/auth/signup", json=payload)
        assert resp.status_code == 422

    def test_missing_school_name_returns_422(self, client: TestClient) -> None:
        payload = _make_signup_payload()
        del payload["school_name"]
        resp = client.post("/api/v1/auth/signup", json=payload)
        assert resp.status_code == 422

    def test_error_response_uses_standard_envelope(self, client: TestClient) -> None:
        payload = _make_signup_payload()
        del payload["email"]
        resp = client.post("/api/v1/auth/signup", json=payload)
        body = resp.json()
        assert "error" in body
        assert body["error"]["code"] == "VALIDATION_ERROR"


# ---------------------------------------------------------------------------
# POST /api/v1/auth/signup — conflict and rate limit
# ---------------------------------------------------------------------------


class TestSignupConflictAndRateLimit:
    def test_duplicate_email_returns_409(self, client: TestClient) -> None:
        from app.exceptions import ConflictError

        with (
            patch(
                "app.routers.auth.create_user",
                new_callable=AsyncMock,
                side_effect=ConflictError("An account with this email already exists."),
            ),
            patch("app.routers.auth._get_redis"),
        ):
            resp = client.post("/api/v1/auth/signup", json=_make_signup_payload())

        assert resp.status_code == 409
        body = resp.json()
        assert body["error"]["code"] == "CONFLICT"

    def test_rate_limit_returns_429(self, client: TestClient) -> None:
        from app.exceptions import RateLimitError

        with (
            patch(
                "app.routers.auth.create_user",
                new_callable=AsyncMock,
                side_effect=RateLimitError("Too many sign-up attempts."),
            ),
            patch("app.routers.auth._get_redis"),
        ):
            resp = client.post("/api/v1/auth/signup", json=_make_signup_payload())

        assert resp.status_code == 429
        body = resp.json()
        assert body["error"]["code"] == "RATE_LIMITED"


# ---------------------------------------------------------------------------
# GET /api/v1/auth/verify-email
# ---------------------------------------------------------------------------


class TestVerifyEmail:
    def test_valid_token_returns_200(self, client: TestClient) -> None:
        fake_user = _make_fake_user()

        with (
            patch(
                "app.routers.auth.verify_email",
                new_callable=AsyncMock,
                return_value=fake_user,
            ),
            patch("app.routers.auth._get_redis"),
        ):
            resp = client.get("/api/v1/auth/verify-email?token=valid_token")

        assert resp.status_code == 200
        body = resp.json()
        assert "data" in body
        assert "message" in body["data"]

    def test_invalid_token_returns_422(self, client: TestClient) -> None:
        from app.exceptions import ValidationError

        with (
            patch(
                "app.routers.auth.verify_email",
                new_callable=AsyncMock,
                side_effect=ValidationError("Token invalid or expired.", field="token"),
            ),
            patch("app.routers.auth._get_redis"),
        ):
            resp = client.get("/api/v1/auth/verify-email?token=bad_token")

        assert resp.status_code == 422
        body = resp.json()
        assert body["error"]["code"] == "VALIDATION_ERROR"

    def test_missing_token_param_returns_422(self, client: TestClient) -> None:
        resp = client.get("/api/v1/auth/verify-email")
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# POST /api/v1/auth/resend-verification
# ---------------------------------------------------------------------------


class TestResendVerification:
    def test_always_returns_202_when_email_not_found(self, client: TestClient) -> None:
        with (
            patch(
                "app.routers.auth.resend_verification",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch("app.routers.auth._get_redis"),
        ):
            resp = client.post(
                "/api/v1/auth/resend-verification",
                json={"email": "notfound@school.edu"},
            )

        assert resp.status_code == 202

    def test_returns_202_and_enqueues_task_when_user_found(self, client: TestClient) -> None:
        fake_user = _make_fake_user()

        with (
            patch(
                "app.routers.auth.resend_verification",
                new_callable=AsyncMock,
                return_value=fake_user,
            ),
            patch(
                "app.routers.auth.generate_verification_token",
                return_value=("raw_token", "hmac_tag"),
            ),
            patch("app.routers.auth.store_verification_token", new_callable=AsyncMock),
            patch("app.routers.auth._get_redis"),
            patch("app.tasks.email.send_verification_email.delay") as mock_delay,
        ):
            resp = client.post(
                "/api/v1/auth/resend-verification",
                json={"email": "teacher@school.edu"},
            )

        assert resp.status_code == 202
        mock_delay.assert_called_once()

    def test_rate_limit_returns_429(self, client: TestClient) -> None:
        from app.exceptions import RateLimitError

        with (
            patch(
                "app.routers.auth.resend_verification",
                new_callable=AsyncMock,
                side_effect=RateLimitError("Too many resend requests."),
            ),
            patch("app.routers.auth._get_redis"),
        ):
            resp = client.post(
                "/api/v1/auth/resend-verification",
                json={"email": "teacher@school.edu"},
            )

        assert resp.status_code == 429

    def test_missing_email_returns_422(self, client: TestClient) -> None:
        resp = client.post("/api/v1/auth/resend-verification", json={})
        assert resp.status_code == 422

    def test_invalid_email_returns_422(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/auth/resend-verification",
            json={"email": "not-an-email"},
        )
        assert resp.status_code == 422
