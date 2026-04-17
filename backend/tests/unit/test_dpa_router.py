"""Unit tests for POST /api/v1/contact/dpa-request."""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app(), raise_server_exceptions=False)


def _make_dpa_payload(**overrides: object) -> dict:
    base = {
        "name": "Jane Smith",
        "email": "jane@district.edu",
        "school_name": "Example Unified School District",
        "district": "Example Unified",
        "message": "We use the SDPC model DPA — please review and sign.",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestSubmitDpaRequestHappyPath:
    def test_returns_201(self, client: TestClient) -> None:
        fake_dpa = MagicMock()
        fake_dpa.id = uuid.uuid4()
        fake_dpa.created_at = datetime.now(UTC)

        with (
            patch(
                "app.routers.contact.create_dpa_request",
                new_callable=AsyncMock,
                return_value=fake_dpa,
            ),
            patch("app.routers.contact._get_redis"),
            patch("app.tasks.email.send_dpa_request_notification.delay"),
        ):
            resp = client.post(
                "/api/v1/contact/dpa-request",
                json=_make_dpa_payload(),
            )

        assert resp.status_code == 201, f"Got {resp.status_code}: {resp.text}"

    def test_returns_data_envelope(self, client: TestClient) -> None:
        fake_id = uuid.uuid4()
        fake_dpa = MagicMock()
        fake_dpa.id = fake_id
        fake_dpa.created_at = datetime.now(UTC)

        with (
            patch(
                "app.routers.contact.create_dpa_request",
                new_callable=AsyncMock,
                return_value=fake_dpa,
            ),
            patch("app.routers.contact._get_redis"),
            patch("app.tasks.email.send_dpa_request_notification.delay"),
        ):
            resp = client.post(
                "/api/v1/contact/dpa-request",
                json=_make_dpa_payload(),
            )

        body = resp.json()
        assert "data" in body, f"Missing 'data' key: {body}"
        assert body["data"]["id"] == str(fake_id)

    def test_optional_fields_can_be_omitted(self, client: TestClient) -> None:
        fake_dpa = MagicMock()
        fake_dpa.id = uuid.uuid4()
        fake_dpa.created_at = datetime.now(UTC)

        with (
            patch(
                "app.routers.contact.create_dpa_request",
                new_callable=AsyncMock,
                return_value=fake_dpa,
            ),
            patch("app.routers.contact._get_redis"),
            patch("app.tasks.email.send_dpa_request_notification.delay"),
        ):
            resp = client.post(
                "/api/v1/contact/dpa-request",
                json={
                    "name": "Bob Admin",
                    "email": "bob@school.edu",
                    "school_name": "Bob Elementary",
                },
            )

        assert resp.status_code == 201, f"Got {resp.status_code}: {resp.text}"


# ---------------------------------------------------------------------------
# Validation errors
# ---------------------------------------------------------------------------


class TestSubmitDpaRequestValidation:
    def test_missing_name_returns_422(self, client: TestClient) -> None:
        payload = _make_dpa_payload()
        del payload["name"]
        resp = client.post("/api/v1/contact/dpa-request", json=payload)
        assert resp.status_code == 422

    def test_missing_email_returns_422(self, client: TestClient) -> None:
        payload = _make_dpa_payload()
        del payload["email"]
        resp = client.post("/api/v1/contact/dpa-request", json=payload)
        assert resp.status_code == 422

    def test_invalid_email_returns_422(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/contact/dpa-request",
            json=_make_dpa_payload(email="not-an-email"),
        )
        assert resp.status_code == 422, f"Got {resp.status_code}"

    def test_missing_school_name_returns_422(self, client: TestClient) -> None:
        payload = _make_dpa_payload()
        del payload["school_name"]
        resp = client.post("/api/v1/contact/dpa-request", json=payload)
        assert resp.status_code == 422

    def test_message_too_long_returns_422(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/contact/dpa-request",
            json=_make_dpa_payload(message="x" * 2001),
        )
        assert resp.status_code == 422, f"Got {resp.status_code}"

    def test_error_response_uses_standard_envelope(self, client: TestClient) -> None:
        payload = _make_dpa_payload()
        del payload["email"]
        resp = client.post("/api/v1/contact/dpa-request", json=payload)
        body = resp.json()
        assert "error" in body, f"Missing 'error' key: {body}"
        assert body["error"]["code"] == "VALIDATION_ERROR"


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------


class TestSubmitDpaRequestRateLimit:
    def test_rate_limit_exceeded_returns_429(self, client: TestClient) -> None:
        from app.exceptions import RateLimitError

        with (
            patch(
                "app.routers.contact.create_dpa_request",
                new_callable=AsyncMock,
                side_effect=RateLimitError("Too many DPA request submissions from this IP."),
            ),
            patch("app.routers.contact._get_redis"),
        ):
            resp = client.post(
                "/api/v1/contact/dpa-request",
                json=_make_dpa_payload(),
            )

        assert resp.status_code == 429, f"Got {resp.status_code}: {resp.text}"
        body = resp.json()
        assert body["error"]["code"] == "RATE_LIMITED"


# ---------------------------------------------------------------------------
# Service-level rate limit enforcement
# ---------------------------------------------------------------------------


class TestDpaServiceRateLimit:
    """Verify that _check_rate_limit is awaited inside create_dpa_request."""

    @pytest.mark.asyncio
    async def test_rate_limit_is_enforced_when_ip_provided(self) -> None:
        from unittest.mock import AsyncMock

        from app.exceptions import RateLimitError
        from app.schemas.dpa import DpaRequestCreate
        from app.services.dpa import create_dpa_request

        payload = DpaRequestCreate(
            name="Test Admin",
            email="admin@school.edu",
            school_name="Test School District",
        )

        mock_db = AsyncMock()
        mock_redis = AsyncMock()
        mock_redis.incr = AsyncMock(return_value=4)  # exceeds limit of 3
        mock_redis.expire = AsyncMock()

        with pytest.raises(RateLimitError):
            await create_dpa_request(mock_db, mock_redis, payload, submitter_ip="1.2.3.4")

        mock_redis.incr.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_rate_limit_skipped_when_no_ip(self) -> None:
        from unittest.mock import AsyncMock, MagicMock

        from app.schemas.dpa import DpaRequestCreate
        from app.services.dpa import create_dpa_request

        payload = DpaRequestCreate(
            name="Test Admin",
            email="admin@school.edu",
            school_name="Test School District",
        )

        mock_db = AsyncMock()
        fake_req = MagicMock()
        fake_req.id = uuid.uuid4()
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock(return_value=fake_req)
        added: list = []
        mock_db.add = lambda obj: added.append(obj)

        mock_redis = AsyncMock()

        await create_dpa_request(mock_db, mock_redis, payload, submitter_ip=None)

        mock_redis.incr.assert_not_called()
