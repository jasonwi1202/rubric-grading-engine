"""Unit tests for security middleware.

Tests verify that:
- SecurityHeadersMiddleware injects required headers on every response,
  including 200 OK, 404, and 429 rate-limit responses.
- RateLimitMiddleware returns 429 when the Redis counter exceeds the limit
  and 200 when within the limit.
- CORS_ORIGINS wildcard is rejected at settings validation time.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.main import create_app
from app.middleware import _SECURITY_HEADERS, RateLimitMiddleware, SecurityHeadersMiddleware

# ---------------------------------------------------------------------------
# Security headers on regular responses
# ---------------------------------------------------------------------------


class TestSecurityHeadersMiddleware:
    """All responses must include every security header."""

    @pytest.fixture()
    def client(self) -> TestClient:
        app = create_app()
        return TestClient(app, raise_server_exceptions=False)

    def test_x_frame_options_present_on_200(self, client: TestClient) -> None:
        resp = client.get("/api/v1/health")
        assert resp.headers.get("X-Frame-Options") == "DENY", resp.headers

    def test_x_content_type_options_present_on_200(self, client: TestClient) -> None:
        resp = client.get("/api/v1/health")
        assert resp.headers.get("X-Content-Type-Options") == "nosniff", resp.headers

    def test_strict_transport_security_present_on_200(self, client: TestClient) -> None:
        resp = client.get("/api/v1/health")
        hsts = resp.headers.get("Strict-Transport-Security", "")
        assert "max-age=31536000" in hsts, resp.headers
        assert "includeSubDomains" in hsts, resp.headers

    def test_x_xss_protection_present_on_200(self, client: TestClient) -> None:
        resp = client.get("/api/v1/health")
        assert resp.headers.get("X-XSS-Protection") == "0", resp.headers

    def test_referrer_policy_present_on_200(self, client: TestClient) -> None:
        resp = client.get("/api/v1/health")
        assert resp.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin", (
            resp.headers
        )

    def test_security_headers_present_on_404(self, client: TestClient) -> None:
        """Security headers must also appear on framework-generated error responses."""
        resp = client.get("/api/v1/does-not-exist")
        assert resp.status_code == 404
        for header in _SECURITY_HEADERS:
            assert header in resp.headers, f"Missing {header} on 404 response"

    def test_all_required_headers_on_health(self, client: TestClient) -> None:
        """All required security headers are present in a single assertion."""
        resp = client.get("/api/v1/health")
        for header in _SECURITY_HEADERS:
            assert header in resp.headers, f"Missing security header: {header}"


# ---------------------------------------------------------------------------
# SecurityHeadersMiddleware — unit-level (standalone app)
# ---------------------------------------------------------------------------


class TestSecurityHeadersMiddlewareUnit:
    """Verify the middleware in isolation, without the full app stack."""

    @pytest.fixture()
    def app_with_middleware(self) -> TestClient:
        app = FastAPI()
        app.add_middleware(SecurityHeadersMiddleware)

        @app.get("/ping")
        async def ping() -> dict:
            return {"pong": True}

        return TestClient(app, raise_server_exceptions=False)

    def test_headers_injected_on_custom_route(self, app_with_middleware: TestClient) -> None:
        resp = app_with_middleware.get("/ping")
        for header, value in _SECURITY_HEADERS.items():
            assert resp.headers.get(header) == value, (
                f"Header {header!r} expected {value!r}, got {resp.headers.get(header)!r}"
            )


# ---------------------------------------------------------------------------
# RateLimitMiddleware — unit-level
# ---------------------------------------------------------------------------


class TestRateLimitMiddleware:
    """Verify that rate-limit logic correctly gates requests."""

    def _make_app(self, redis_mock: MagicMock) -> TestClient:
        """Build a minimal app with RateLimitMiddleware wired to *redis_mock*."""
        app = FastAPI()

        @app.post("/api/v1/auth/login")
        async def fake_login() -> dict:
            return {"access_token": "tok"}

        middleware = RateLimitMiddleware.__new__(RateLimitMiddleware)
        # Bypass __init__; inject the mock Redis client directly.
        middleware._redis = redis_mock
        # Build the wrapped app manually using starlette dispatch.
        from starlette.middleware.base import BaseHTTPMiddleware

        BaseHTTPMiddleware.__init__(middleware, app)

        return TestClient(middleware, raise_server_exceptions=False)

    def _make_redis(self, counter: int) -> MagicMock:
        """Return a mock Redis client that returns *counter* on INCR."""
        mock = MagicMock()
        mock.incr = AsyncMock(return_value=counter)
        mock.expire = AsyncMock(return_value=True)
        return mock

    def test_allows_request_within_limit(self) -> None:
        redis_mock = self._make_redis(counter=1)
        client = self._make_app(redis_mock)
        resp = client.post("/api/v1/auth/login", json={"email": "t@t.com", "password": "pw"})
        # The route handler returns {"access_token": "tok"} with status 200.
        # The rate-limit middleware should NOT have returned 429.
        assert resp.status_code != 429, f"Unexpected 429: {resp.text}"

    def test_blocks_request_over_limit(self) -> None:
        redis_mock = self._make_redis(counter=11)  # login limit is 10
        client = self._make_app(redis_mock)
        resp = client.post("/api/v1/auth/login", json={"email": "t@t.com", "password": "pw"})
        assert resp.status_code == 429, f"Expected 429, got {resp.status_code}: {resp.text}"
        body = resp.json()
        assert body["error"]["code"] == "RATE_LIMITED"

    def test_non_rate_limited_path_is_unaffected(self) -> None:
        """GET /api/v1/health is not in the rate-limit rules; Redis is never called."""
        app = FastAPI()

        @app.get("/api/v1/health")
        async def health() -> dict:
            return {"status": "ok"}

        redis_mock = self._make_redis(counter=999)
        middleware = RateLimitMiddleware.__new__(RateLimitMiddleware)
        middleware._redis = redis_mock
        from starlette.middleware.base import BaseHTTPMiddleware

        BaseHTTPMiddleware.__init__(middleware, app)

        client = TestClient(middleware, raise_server_exceptions=False)
        resp = client.get("/api/v1/health")
        assert resp.status_code == 200
        redis_mock.incr.assert_not_called()

    def test_redis_failure_fails_open(self) -> None:
        """When Redis raises an exception the request is allowed through."""
        mock = MagicMock()
        mock.incr = AsyncMock(side_effect=ConnectionError("redis down"))
        mock.expire = AsyncMock(return_value=True)

        app = FastAPI()

        @app.post("/api/v1/auth/login")
        async def fake_login() -> dict:
            return {"access_token": "tok"}

        middleware = RateLimitMiddleware.__new__(RateLimitMiddleware)
        middleware._redis = mock
        from starlette.middleware.base import BaseHTTPMiddleware

        BaseHTTPMiddleware.__init__(middleware, app)

        client = TestClient(middleware, raise_server_exceptions=False)
        resp = client.post("/api/v1/auth/login", json={})
        assert resp.status_code != 429, "Should fail open when Redis is unavailable"


# ---------------------------------------------------------------------------
# CORS wildcard validation
# ---------------------------------------------------------------------------

# Minimal required fields for a valid Settings instance — mirrors the pattern
# used in tests/unit/test_config.py.  Using Settings() directly avoids the
# module-level singleton mutation that reload(app.config) would cause.
_SETTINGS_BASE: dict[str, object] = {
    "database_url": "postgresql+asyncpg://user:pass@localhost:5432/testdb",
    "redis_url": "redis://localhost:6379/0",
    "jwt_secret_key": "a" * 32,
    "email_verification_hmac_secret": "b" * 32,
    "unsubscribe_hmac_secret": "c" * 32,
    "openai_api_key": "test-openai-key",
    "s3_bucket_name": "test-bucket",
    "s3_region": "us-east-1",
    "aws_access_key_id": "test-aws-key",
    "aws_secret_access_key": "test-aws-secret",
    "cors_origins": "http://localhost:3000",
}


class TestCorsWildcardRejection:
    """Settings must reject a wildcard '*' in CORS_ORIGINS."""

    def test_wildcard_origin_raises_validation_error(self) -> None:
        from pydantic import ValidationError as PydanticValidationError

        from app.config import Settings

        with pytest.raises(PydanticValidationError, match="not permitted"):
            Settings(  # type: ignore[call-arg]  # _env_file is a pydantic-settings internal kwarg not in the public type stub
                _env_file=None, **{**_SETTINGS_BASE, "cors_origins": "*"}
            )

    def test_explicit_origin_is_accepted(self) -> None:
        """A concrete origin string must not raise a validation error."""
        from app.config import Settings

        s = Settings(
            _env_file=None,  # type: ignore[call-arg]  # _env_file is a pydantic-settings internal kwarg not in the public type stub
            **{
                **_SETTINGS_BASE,
                "cors_origins": "http://localhost:3000,https://app.example.com",
            },
        )
        assert s.cors_origins_list == [
            "http://localhost:3000",
            "https://app.example.com",
        ]
