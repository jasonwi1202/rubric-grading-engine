"""Unit tests for POST /api/v1/contact/inquiry."""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app(), raise_server_exceptions=False)


def _make_inquiry_payload(**overrides: object) -> dict:
    base = {
        "name": "Jane Smith",
        "email": "jane@example-school.edu",
        "school_name": "Example High School",
        "district": "Example Unified",
        "estimated_teachers": 40,
        "message": "We are interested in the School tier.",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestSubmitInquiryHappyPath:
    def test_returns_201(self, client: TestClient) -> None:
        fake_inquiry = MagicMock()
        fake_inquiry.id = uuid.uuid4()
        fake_inquiry.created_at = datetime.now(UTC)

        with (
            patch(
                "app.routers.contact.create_inquiry",
                new_callable=AsyncMock,
                return_value=fake_inquiry,
            ),
            patch("app.routers.contact._get_redis"),
            patch("app.tasks.email.send_inquiry_notification.delay"),
        ):
            resp = client.post(
                "/api/v1/contact/inquiry",
                json=_make_inquiry_payload(),
            )

        assert resp.status_code == 201, f"Got {resp.status_code}: {resp.text}"

    def test_returns_data_envelope(self, client: TestClient) -> None:
        fake_id = uuid.uuid4()
        fake_inquiry = MagicMock()
        fake_inquiry.id = fake_id
        fake_inquiry.created_at = datetime.now(UTC)

        with (
            patch(
                "app.routers.contact.create_inquiry",
                new_callable=AsyncMock,
                return_value=fake_inquiry,
            ),
            patch("app.routers.contact._get_redis"),
            patch("app.tasks.email.send_inquiry_notification.delay"),
        ):
            resp = client.post(
                "/api/v1/contact/inquiry",
                json=_make_inquiry_payload(),
            )

        body = resp.json()
        assert "data" in body, f"Missing 'data' key: {body}"
        assert body["data"]["id"] == str(fake_id)

    def test_optional_fields_can_be_omitted(self, client: TestClient) -> None:
        fake_inquiry = MagicMock()
        fake_inquiry.id = uuid.uuid4()
        fake_inquiry.created_at = datetime.now(UTC)

        with (
            patch(
                "app.routers.contact.create_inquiry",
                new_callable=AsyncMock,
                return_value=fake_inquiry,
            ),
            patch("app.routers.contact._get_redis"),
            patch("app.tasks.email.send_inquiry_notification.delay"),
        ):
            resp = client.post(
                "/api/v1/contact/inquiry",
                json={"name": "Bob", "email": "bob@school.edu", "school_name": "Bob School"},
            )

        assert resp.status_code == 201, f"Got {resp.status_code}: {resp.text}"


# ---------------------------------------------------------------------------
# Validation errors
# ---------------------------------------------------------------------------


class TestSubmitInquiryValidation:
    def test_missing_name_returns_422(self, client: TestClient) -> None:
        payload = _make_inquiry_payload()
        del payload["name"]
        resp = client.post("/api/v1/contact/inquiry", json=payload)
        assert resp.status_code == 422

    def test_missing_email_returns_422(self, client: TestClient) -> None:
        payload = _make_inquiry_payload()
        del payload["email"]
        resp = client.post("/api/v1/contact/inquiry", json=payload)
        assert resp.status_code == 422

    def test_invalid_email_returns_422(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/contact/inquiry",
            json=_make_inquiry_payload(email="not-an-email"),
        )
        assert resp.status_code == 422, f"Got {resp.status_code}"

    def test_missing_school_name_returns_422(self, client: TestClient) -> None:
        payload = _make_inquiry_payload()
        del payload["school_name"]
        resp = client.post("/api/v1/contact/inquiry", json=payload)
        assert resp.status_code == 422

    def test_negative_estimated_teachers_returns_422(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/contact/inquiry",
            json=_make_inquiry_payload(estimated_teachers=-1),
        )
        assert resp.status_code == 422

    def test_error_response_uses_standard_envelope(self, client: TestClient) -> None:
        payload = _make_inquiry_payload()
        del payload["email"]
        resp = client.post("/api/v1/contact/inquiry", json=payload)
        body = resp.json()
        assert "error" in body, f"Missing 'error' key: {body}"
        assert body["error"]["code"] == "VALIDATION_ERROR"


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------


class TestSubmitInquiryRateLimit:
    def test_rate_limit_exceeded_returns_429(self, client: TestClient) -> None:
        from app.exceptions import RateLimitError

        with (
            patch(
                "app.routers.contact.create_inquiry",
                new_callable=AsyncMock,
                side_effect=RateLimitError("Too many inquiry submissions from this IP."),
            ),
            patch("app.routers.contact._get_redis"),
        ):
            resp = client.post(
                "/api/v1/contact/inquiry",
                json=_make_inquiry_payload(),
            )

        assert resp.status_code == 429, f"Got {resp.status_code}: {resp.text}"
        body = resp.json()
        assert body["error"]["code"] == "RATE_LIMITED"


# ---------------------------------------------------------------------------
# Service-level rate limit enforcement (regression guard for missing await)
# ---------------------------------------------------------------------------


class TestContactServiceRateLimit:
    """Verify that _check_rate_limit is actually awaited inside create_inquiry.

    A previous bug had ``_check_rate_limit(...)`` called without ``await``,
    meaning the coroutine was created but never executed and rate limiting was
    silently skipped.  These tests use the service directly to catch that
    regression without going through the router.
    """

    @pytest.mark.asyncio
    async def test_rate_limit_is_enforced_when_ip_provided(self) -> None:
        """create_inquiry must raise RateLimitError once the counter exceeds max."""
        from unittest.mock import AsyncMock

        from app.exceptions import RateLimitError
        from app.schemas.contact import ContactInquiryRequest
        from app.services.contact import create_inquiry

        payload = ContactInquiryRequest(
            name="Test School",
            email="test@school.edu",
            school_name="Test School",
        )

        mock_db = AsyncMock()
        mock_redis = AsyncMock()
        # Simulate counter already at limit+1 (6th request)
        mock_redis.incr = AsyncMock(return_value=6)
        mock_redis.expire = AsyncMock()

        with pytest.raises(RateLimitError):
            await create_inquiry(mock_db, mock_redis, payload, submitter_ip="1.2.3.4")

        # Verify Redis was actually called — proves the await was executed
        mock_redis.incr.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_rate_limit_skipped_when_no_ip(self) -> None:
        """create_inquiry must not call Redis when submitter_ip is None."""
        from unittest.mock import AsyncMock, MagicMock

        from app.schemas.contact import ContactInquiryRequest
        from app.services.contact import create_inquiry

        payload = ContactInquiryRequest(
            name="Test School",
            email="test@school.edu",
            school_name="Test School",
        )

        mock_db = AsyncMock()
        # Fake the DB commit / refresh chain
        fake_inquiry = MagicMock()
        fake_inquiry.id = uuid.uuid4()
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock(return_value=fake_inquiry)
        # Attach add so it captures the inquiry
        added: list = []
        mock_db.add = lambda obj: added.append(obj)

        mock_redis = AsyncMock()

        await create_inquiry(mock_db, mock_redis, payload, submitter_ip=None)

        mock_redis.incr.assert_not_called()
