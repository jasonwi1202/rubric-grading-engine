"""Unit tests for RequestMetricsMiddleware.

Verifies that:
- Structured ``http.request`` log events are emitted for normal requests.
- Probe paths (``/api/v1/health``, ``/api/v1/readiness``) are excluded.
- Query strings are never logged.
- ``latency_ms`` is a non-negative integer.
- ``status_code`` reflects the actual HTTP response code.
- No student PII or sensitive values appear in the log event.

Security:
- No student PII in fixtures.
- No credential-format strings.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app.main import create_app
from app.middleware import _METRICS_EXCLUDED_PATHS, RateLimitMiddleware, RequestMetricsMiddleware

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture()
def client() -> TestClient:
    """Application client wrapping the real app (no dependency mocks at fixture level)."""
    return TestClient(create_app(), raise_server_exceptions=False)


def _make_app_with_route(status_code: int = 200) -> FastAPI:
    """Create a fresh app with a GET /test-metrics route returning *status_code*."""
    app = create_app()

    async def _handler() -> JSONResponse:
        return JSONResponse(status_code=status_code, content={"ok": "true"})

    app.routes.append(APIRoute("/test-metrics", _handler, methods=["GET"]))
    return app


# ---------------------------------------------------------------------------
# Middleware registration
# ---------------------------------------------------------------------------


class TestRequestMetricsMiddlewareRegistration:
    def test_middleware_is_registered_in_app(self) -> None:
        """RequestMetricsMiddleware must appear in the middleware stack."""
        app = create_app()
        # user_middleware stores Middleware() wrappers; cls attr holds the actual class.
        middleware_classes = [
            getattr(m, "cls", None) for m in getattr(app, "user_middleware", [])
        ]
        assert RequestMetricsMiddleware in middleware_classes, (
            f"RequestMetricsMiddleware not found in middleware stack: {middleware_classes}"
        )


# ---------------------------------------------------------------------------
# Excluded probe paths
# ---------------------------------------------------------------------------


class TestMetricsExcludedPaths:
    def test_excluded_paths_set_contains_health(self) -> None:
        assert "/api/v1/health" in _METRICS_EXCLUDED_PATHS

    def test_excluded_paths_set_contains_readiness(self) -> None:
        assert "/api/v1/readiness" in _METRICS_EXCLUDED_PATHS

    def test_health_probe_does_not_emit_metrics_log(
        self, client: TestClient
    ) -> None:
        mock_logger = MagicMock()
        with (
            patch("app.routers.health._check_database", new=AsyncMock(return_value=True)),
            patch("app.routers.health._check_redis", new=AsyncMock(return_value=True)),
            patch("app.middleware.logger", mock_logger),
        ):
            client.get("/api/v1/health")

        for c in mock_logger.info.call_args_list:
            extra = c.kwargs.get("extra", {})
            assert extra.get("event") != "http.request", (
                "No http.request event should be emitted for /api/v1/health"
            )

    def test_readiness_probe_does_not_emit_metrics_log(
        self, client: TestClient
    ) -> None:
        mock_logger = MagicMock()
        with (
            patch("app.routers.health._check_database", new=AsyncMock(return_value=True)),
            patch("app.routers.health._check_redis", new=AsyncMock(return_value=True)),
            patch("app.middleware.logger", mock_logger),
        ):
            client.get("/api/v1/readiness")

        for c in mock_logger.info.call_args_list:
            extra = c.kwargs.get("extra", {})
            assert extra.get("event") != "http.request", (
                "No http.request event should be emitted for /api/v1/readiness"
            )


# ---------------------------------------------------------------------------
# Normal request emission
# ---------------------------------------------------------------------------


class TestRequestMetricsEmission:
    def _get_http_request_extra(self, mock_logger: MagicMock) -> dict | None:
        """Return the extra dict from the first http.request log call, or None."""
        for c in mock_logger.info.call_args_list:
            extra = c.kwargs.get("extra", {})
            if extra.get("event") == "http.request":
                return extra
        return None

    def test_emits_http_request_event_on_normal_request(self) -> None:
        app = _make_app_with_route(200)
        mock_logger = MagicMock()
        with (
            patch("app.middleware.logger", mock_logger),
            TestClient(app, raise_server_exceptions=False) as c,
        ):
            c.get("/test-metrics")
        extra = self._get_http_request_extra(mock_logger)
        assert extra is not None, "Expected an http.request log event"

    def test_event_field_is_http_request(self) -> None:
        app = _make_app_with_route(200)
        mock_logger = MagicMock()
        with (
            patch("app.middleware.logger", mock_logger),
            TestClient(app, raise_server_exceptions=False) as c,
        ):
            c.get("/test-metrics")
        extra = self._get_http_request_extra(mock_logger)
        assert extra is not None
        assert extra["event"] == "http.request"

    def test_method_field_is_get(self) -> None:
        app = _make_app_with_route(200)
        mock_logger = MagicMock()
        with (
            patch("app.middleware.logger", mock_logger),
            TestClient(app, raise_server_exceptions=False) as c,
        ):
            c.get("/test-metrics")
        extra = self._get_http_request_extra(mock_logger)
        assert extra is not None
        assert extra["method"] == "GET"

    def test_path_field_matches_route(self) -> None:
        app = _make_app_with_route(200)
        mock_logger = MagicMock()
        with (
            patch("app.middleware.logger", mock_logger),
            TestClient(app, raise_server_exceptions=False) as c,
        ):
            c.get("/test-metrics")
        extra = self._get_http_request_extra(mock_logger)
        assert extra is not None
        assert extra["path"] == "/test-metrics"

    def test_status_code_field_reflects_response(self) -> None:
        app = _make_app_with_route(404)
        mock_logger = MagicMock()
        with (
            patch("app.middleware.logger", mock_logger),
            TestClient(app, raise_server_exceptions=False) as c,
        ):
            c.get("/test-metrics")
        extra = self._get_http_request_extra(mock_logger)
        assert extra is not None
        assert extra["status_code"] == 404

    def test_latency_ms_is_non_negative_integer(self) -> None:
        app = _make_app_with_route(200)
        mock_logger = MagicMock()
        with (
            patch("app.middleware.logger", mock_logger),
            TestClient(app, raise_server_exceptions=False) as c,
        ):
            c.get("/test-metrics")
        extra = self._get_http_request_extra(mock_logger)
        assert extra is not None
        latency = extra.get("latency_ms")
        assert isinstance(latency, int), f"latency_ms must be int, got {type(latency)}"
        assert latency >= 0, f"latency_ms must be non-negative, got {latency}"

    def test_query_string_absent_from_path_field(self) -> None:
        """Query strings must never appear in the logged path."""
        app = _make_app_with_route(200)
        mock_logger = MagicMock()
        with (
            patch("app.middleware.logger", mock_logger),
            TestClient(app, raise_server_exceptions=False) as c,
        ):
            c.get("/test-metrics?token=secret-value")
        extra = self._get_http_request_extra(mock_logger)
        assert extra is not None
        logged_path = extra.get("path", "")
        assert "secret-value" not in logged_path, (
            f"Query string leaked into logged path: {logged_path!r}"
        )
        assert "?" not in logged_path, (
            f"Query string separator '?' present in logged path: {logged_path!r}"
        )

    def test_emits_event_for_post_method(self) -> None:
        app = create_app()

        async def _post_handler() -> JSONResponse:
            return JSONResponse(status_code=200, content={"ok": "true"})

        app.routes.append(APIRoute("/test-post", _post_handler, methods=["POST"]))
        mock_logger = MagicMock()
        with (
            patch("app.middleware.logger", mock_logger),
            TestClient(app, raise_server_exceptions=False) as c,
        ):
            c.post("/test-post", json={})
        extra = self._get_http_request_extra(mock_logger)
        assert extra is not None
        assert extra["method"] == "POST"

    def test_emits_event_for_5xx_responses(self) -> None:
        app = _make_app_with_route(500)
        mock_logger = MagicMock()
        with (
            patch("app.middleware.logger", mock_logger),
            TestClient(app, raise_server_exceptions=False) as c,
        ):
            c.get("/test-metrics")
        extra = self._get_http_request_extra(mock_logger)
        assert extra is not None
        assert extra["status_code"] == 500


# ---------------------------------------------------------------------------
# 429 capture regression — middleware ordering guard
# ---------------------------------------------------------------------------


class TestMetrics429Capture:
    """Regression guard for middleware ordering.

    ``RequestMetricsMiddleware`` sits **outside** ``RateLimitMiddleware`` so
    that 429 responses emitted by the rate-limit layer are still captured.
    If the order were ever swapped — metrics inside rate-limit — the rate-limit
    short-circuit would bypass the metrics layer and the auth-flood signal
    would silently disappear.
    """

    def _get_http_request_extra(self, mock_logger: MagicMock) -> dict | None:
        for c in mock_logger.info.call_args_list:
            extra = c.kwargs.get("extra", {})
            if extra.get("event") == "http.request":
                return extra
        return None

    def test_captures_429_when_rate_limit_middleware_short_circuits(self) -> None:
        """http.request event must be emitted even when RateLimitMiddleware returns 429."""
        from fastapi.responses import JSONResponse as _JSONResponse
        from starlette.requests import Request as _Request

        app = create_app()
        mock_logger = MagicMock()

        # Replace RateLimitMiddleware.dispatch with a function that short-circuits
        # with 429 without calling call_next — exactly the real rate-limit path.
        async def _always_429(
            _self: object,
            request: _Request,
            call_next: object,
        ) -> _JSONResponse:
            return _JSONResponse(
                status_code=429,
                content={"error": {"code": "RATE_LIMITED", "message": "test", "field": None}},
            )

        with (
            patch("app.middleware.logger", mock_logger),
            patch.object(RateLimitMiddleware, "dispatch", _always_429),
            TestClient(app, raise_server_exceptions=False) as c,
        ):
            c.post("/api/v1/auth/login", json={"email": "x@example.com", "password": "pw"})

        extra = self._get_http_request_extra(mock_logger)
        assert extra is not None, (
            "Expected http.request log event for a rate-limited request — "
            "check that RequestMetricsMiddleware is registered outside RateLimitMiddleware"
        )
        assert extra["status_code"] == 429, (
            f"Expected status_code=429, got {extra.get('status_code')}"
        )
