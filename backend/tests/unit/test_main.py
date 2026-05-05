"""Unit tests for the health endpoint and global exception handlers."""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.exceptions import (
    ConflictError,
    ForbiddenError,
    GradeLockedError,
    LLMError,
    LLMParseError,
    NotFoundError,
    ValidationError,
)
from app.main import create_app


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app(), raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------


class TestHealthEndpoint:
    def test_health_returns_200_when_deps_ok(self, client: TestClient) -> None:
        with (
            patch("app.routers.health._check_database", new=AsyncMock(return_value=True)),
            patch("app.routers.health._check_redis", new=AsyncMock(return_value=True)),
        ):
            resp = client.get("/api/v1/health")
        assert resp.status_code == 200, f"Got {resp.status_code}"

    def test_health_returns_503_when_database_down(self, client: TestClient) -> None:
        with (
            patch("app.routers.health._check_database", new=AsyncMock(return_value=False)),
            patch("app.routers.health._check_redis", new=AsyncMock(return_value=True)),
        ):
            resp = client.get("/api/v1/health")
        assert resp.status_code == 503, f"Got {resp.status_code}"

    def test_health_returns_503_when_redis_down(self, client: TestClient) -> None:
        with (
            patch("app.routers.health._check_database", new=AsyncMock(return_value=True)),
            patch("app.routers.health._check_redis", new=AsyncMock(return_value=False)),
        ):
            resp = client.get("/api/v1/health")
        assert resp.status_code == 503, f"Got {resp.status_code}"

    def test_health_body_shape_when_healthy(self, client: TestClient) -> None:
        with (
            patch("app.routers.health._check_database", new=AsyncMock(return_value=True)),
            patch("app.routers.health._check_redis", new=AsyncMock(return_value=True)),
        ):
            resp = client.get("/api/v1/health")
        body = resp.json()["data"]
        assert body["status"] == "ok", f"Got {body}"
        assert body["service"] == "rubric-grading-engine-api", f"Got {body}"
        assert "version" in body, f"Missing 'version' in {body}"
        assert body["dependencies"]["database"] == "ok", f"Got {body}"
        assert body["dependencies"]["redis"] == "ok", f"Got {body}"

    def test_health_body_shape_when_degraded(self, client: TestClient) -> None:
        with (
            patch("app.routers.health._check_database", new=AsyncMock(return_value=False)),
            patch("app.routers.health._check_redis", new=AsyncMock(return_value=False)),
        ):
            resp = client.get("/api/v1/health")
        body = resp.json()["data"]
        assert body["status"] == "degraded", f"Got {body}"
        assert body["service"] == "rubric-grading-engine-api", f"Got {body}"
        assert body["dependencies"]["database"] == "unavailable", f"Got {body}"
        assert body["dependencies"]["redis"] == "unavailable", f"Got {body}"

    def test_health_always_returns_service_and_version(self, client: TestClient) -> None:
        """Response always contains service and version regardless of dep status."""
        with (
            patch("app.routers.health._check_database", new=AsyncMock(return_value=False)),
            patch("app.routers.health._check_redis", new=AsyncMock(return_value=False)),
        ):
            resp = client.get("/api/v1/health")
        body = resp.json()["data"]
        assert "service" in body, f"Missing 'service' key: {body}"
        assert "version" in body, f"Missing 'version' key: {body}"
        assert "dependencies" in body, f"Missing 'dependencies' key: {body}"


# ---------------------------------------------------------------------------
# Readiness endpoint
# ---------------------------------------------------------------------------


class TestReadinessEndpoint:
    def test_readiness_returns_200_when_deps_ok(self, client: TestClient) -> None:
        with (
            patch("app.routers.health._check_database", new=AsyncMock(return_value=True)),
            patch("app.routers.health._check_redis", new=AsyncMock(return_value=True)),
            patch("app.routers.health._check_broker", new=AsyncMock(return_value=True)),
        ):
            resp = client.get("/api/v1/readiness")
        assert resp.status_code == 200, f"Got {resp.status_code}"

    def test_readiness_returns_503_when_database_down(self, client: TestClient) -> None:
        with (
            patch("app.routers.health._check_database", new=AsyncMock(return_value=False)),
            patch("app.routers.health._check_redis", new=AsyncMock(return_value=True)),
            patch("app.routers.health._check_broker", new=AsyncMock(return_value=True)),
        ):
            resp = client.get("/api/v1/readiness")
        assert resp.status_code == 503, f"Got {resp.status_code}"

    def test_readiness_returns_503_when_redis_down(self, client: TestClient) -> None:
        with (
            patch("app.routers.health._check_database", new=AsyncMock(return_value=True)),
            patch("app.routers.health._check_redis", new=AsyncMock(return_value=False)),
            patch("app.routers.health._check_broker", new=AsyncMock(return_value=True)),
        ):
            resp = client.get("/api/v1/readiness")
        assert resp.status_code == 503, f"Got {resp.status_code}"

    def test_readiness_returns_503_when_broker_down(self, client: TestClient) -> None:
        """Broker Redis outage makes service not_ready even if cache Redis is fine."""
        with (
            patch("app.routers.health._check_database", new=AsyncMock(return_value=True)),
            patch("app.routers.health._check_redis", new=AsyncMock(return_value=True)),
            patch("app.routers.health._check_broker", new=AsyncMock(return_value=False)),
        ):
            resp = client.get("/api/v1/readiness")
        assert resp.status_code == 503, f"Got {resp.status_code}"
        assert resp.json()["data"]["status"] == "not_ready"
        assert resp.json()["data"]["dependencies"]["broker"] == "unavailable"

    def test_readiness_body_status_ready_when_healthy(self, client: TestClient) -> None:
        with (
            patch("app.routers.health._check_database", new=AsyncMock(return_value=True)),
            patch("app.routers.health._check_redis", new=AsyncMock(return_value=True)),
            patch("app.routers.health._check_broker", new=AsyncMock(return_value=True)),
        ):
            resp = client.get("/api/v1/readiness")
        body = resp.json()["data"]
        assert body["status"] == "ready", f"Got {body}"
        assert body["dependencies"]["broker"] == "ok", f"Got {body}"

    def test_readiness_body_status_not_ready_when_degraded(self, client: TestClient) -> None:
        with (
            patch("app.routers.health._check_database", new=AsyncMock(return_value=False)),
            patch("app.routers.health._check_redis", new=AsyncMock(return_value=False)),
            patch("app.routers.health._check_broker", new=AsyncMock(return_value=False)),
        ):
            resp = client.get("/api/v1/readiness")
        body = resp.json()["data"]
        assert body["status"] == "not_ready", f"Got {body}"

    def test_readiness_body_contains_service_and_version(self, client: TestClient) -> None:
        with (
            patch("app.routers.health._check_database", new=AsyncMock(return_value=True)),
            patch("app.routers.health._check_redis", new=AsyncMock(return_value=True)),
            patch("app.routers.health._check_broker", new=AsyncMock(return_value=True)),
        ):
            resp = client.get("/api/v1/readiness")
        body = resp.json()["data"]
        assert "service" in body, f"Missing 'service' key: {body}"
        assert "version" in body, f"Missing 'version' key: {body}"
        assert "dependencies" in body, f"Missing 'dependencies' key: {body}"

    def test_readiness_no_auth_required(self, client: TestClient) -> None:
        """Readiness probe must be reachable without any auth header."""
        with (
            patch("app.routers.health._check_database", new=AsyncMock(return_value=True)),
            patch("app.routers.health._check_redis", new=AsyncMock(return_value=True)),
            patch("app.routers.health._check_broker", new=AsyncMock(return_value=True)),
        ):
            resp = client.get("/api/v1/readiness")
        assert resp.status_code != 401, "Readiness probe must not require auth"
        assert resp.status_code != 403, "Readiness probe must not require auth"


# ---------------------------------------------------------------------------
# Correlation ID header propagation
# ---------------------------------------------------------------------------



class TestCorrelationId:
    def test_response_includes_correlation_id_header(self, client: TestClient) -> None:
        with (
            patch("app.routers.health._check_database", new=AsyncMock(return_value=True)),
            patch("app.routers.health._check_redis", new=AsyncMock(return_value=True)),
        ):
            resp = client.get("/api/v1/health")
        assert "X-Correlation-Id" in resp.headers, (
            f"X-Correlation-Id missing from response headers: {dict(resp.headers)}"
        )

    def test_client_supplied_correlation_id_is_echoed(self, client: TestClient) -> None:
        # Must be a canonical UUID4 string for the middleware to accept it.
        supplied_id = "550e8400-e29b-41d4-a716-446655440000"
        with (
            patch("app.routers.health._check_database", new=AsyncMock(return_value=True)),
            patch("app.routers.health._check_redis", new=AsyncMock(return_value=True)),
        ):
            resp = client.get(
                "/api/v1/health",
                headers={"X-Correlation-Id": supplied_id},
            )
        # The middleware normalizes to lowercase UUID4 form.
        assert resp.headers.get("X-Correlation-Id") == supplied_id.lower(), (
            f"Expected echoed ID {supplied_id!r}, got {resp.headers.get('X-Correlation-Id')!r}"
        )

    def test_invalid_correlation_id_header_is_replaced(self, client: TestClient) -> None:
        """Non-UUID4 X-Correlation-Id is rejected and a fresh UUID4 is generated."""
        with (
            patch("app.routers.health._check_database", new=AsyncMock(return_value=True)),
            patch("app.routers.health._check_redis", new=AsyncMock(return_value=True)),
        ):
            resp = client.get(
                "/api/v1/health",
                headers={"X-Correlation-Id": "not-a-uuid"},
            )
        cid = resp.headers.get("X-Correlation-Id", "")
        # The original value must not be echoed back.
        assert cid != "not-a-uuid", f"Invalid correlation ID was echoed: {cid!r}"
        assert cid, "Expected a generated UUID4 but got empty string"

    def test_missing_correlation_id_header_generates_one(self, client: TestClient) -> None:
        with (
            patch("app.routers.health._check_database", new=AsyncMock(return_value=True)),
            patch("app.routers.health._check_redis", new=AsyncMock(return_value=True)),
        ):
            resp = client.get("/api/v1/health")
        cid = resp.headers.get("X-Correlation-Id", "")
        assert cid, "Expected a generated correlation ID but got empty string"


# ---------------------------------------------------------------------------
# Exception handler helpers
# ---------------------------------------------------------------------------


def _make_client_with_route(exc: Exception) -> TestClient:
    """Create a fresh app with an extra route that raises *exc*."""
    from fastapi.routing import APIRoute

    app = create_app()

    async def _raise() -> None:
        raise exc

    app.routes.append(APIRoute("/test-error", _raise, methods=["GET"]))
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Domain exception → HTTP status mapping
# ---------------------------------------------------------------------------


class TestExceptionHandlers:
    def test_not_found_returns_404(self) -> None:
        client = _make_client_with_route(NotFoundError("essay not found"))
        resp = client.get("/test-error")
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "NOT_FOUND"

    def test_forbidden_returns_403(self) -> None:
        client = _make_client_with_route(ForbiddenError("access denied"))
        resp = client.get("/test-error")
        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "FORBIDDEN"

    def test_conflict_returns_409(self) -> None:
        client = _make_client_with_route(ConflictError("already exists"))
        resp = client.get("/test-error")
        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "CONFLICT"

    def test_grade_locked_returns_409_with_specific_code(self) -> None:
        client = _make_client_with_route(GradeLockedError("grade is locked"))
        resp = client.get("/test-error")
        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "GRADE_LOCKED"

    def test_validation_error_returns_422(self) -> None:
        client = _make_client_with_route(ValidationError("invalid weight", field="weight"))
        resp = client.get("/test-error")
        assert resp.status_code == 422
        body = resp.json()
        assert body["error"]["code"] == "VALIDATION_ERROR"
        assert body["error"]["field"] == "weight"

    def test_llm_error_returns_503(self) -> None:
        client = _make_client_with_route(LLMError("openai timeout"))
        resp = client.get("/test-error")
        assert resp.status_code == 503
        assert resp.json()["error"]["code"] == "LLM_UNAVAILABLE"

    def test_llm_parse_error_returns_500_with_specific_code(self) -> None:
        client = _make_client_with_route(LLMParseError("bad json"))
        resp = client.get("/test-error")
        assert resp.status_code == 500
        assert resp.json()["error"]["code"] == "LLM_PARSE_ERROR"

    def test_unhandled_exception_returns_500_structured(self) -> None:
        client = _make_client_with_route(RuntimeError("something broke"))
        resp = client.get("/test-error")
        assert resp.status_code == 500
        body = resp.json()
        assert "error" in body
        assert body["error"]["code"] == "INTERNAL_ERROR"

    def test_error_envelope_shape(self) -> None:
        """Every error response has the required envelope keys."""
        client = _make_client_with_route(NotFoundError("missing"))
        resp = client.get("/test-error")
        error = resp.json()["error"]
        assert "code" in error
        assert "message" in error
        assert "field" in error

    def test_request_validation_error_returns_422_envelope(self) -> None:
        """RequestValidationError is normalized to the structured error envelope."""
        from fastapi import Query
        from fastapi.routing import APIRoute

        app = create_app()

        async def _needs_param(count: int = Query(...)) -> dict[str, int]:
            return {"count": count}

        app.routes.append(APIRoute("/test-validation", _needs_param, methods=["GET"]))
        c = TestClient(app, raise_server_exceptions=False)
        resp = c.get("/test-validation")  # omit required `count` param
        assert resp.status_code == 422, f"Got {resp.status_code}"
        body = resp.json()
        assert body["error"]["code"] == "VALIDATION_ERROR", f"Got {body}"
        # Field name should not include leading 'query' prefix
        assert body["error"]["field"] == "count", f"Got field={body['error']['field']}"

    def test_unknown_route_returns_404_envelope(self, client: TestClient) -> None:
        """Framework 404 for an unknown route uses the structured error envelope."""
        resp = client.get("/api/v1/does-not-exist")
        assert resp.status_code == 404, f"Got {resp.status_code}"
        body = resp.json()
        assert body["error"]["code"] == "NOT_FOUND", f"Got {body}"

    def test_unhandled_exception_does_not_expose_exc_message(self) -> None:
        """Error responses for unexpected exceptions must not contain str(exc)."""
        secret_message = "secret-db-password-was-leaked"
        client = _make_client_with_route(RuntimeError(secret_message))
        resp = client.get("/test-error")
        assert resp.status_code == 500
        # The raw exception message must not appear anywhere in the response body.
        assert secret_message not in resp.text, (
            f"Exception message leaked into response: {resp.text}"
        )

    def test_unhandled_exception_log_does_not_contain_exc_message(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Unhandled exception handler logs error_type only — not the exception message."""
        sensitive_token = "<student_name>"
        client = _make_client_with_route(RuntimeError(f"essay by {sensitive_token} was invalid"))
        with caplog.at_level(logging.ERROR):
            client.get("/test-error")
        # The sensitive token must not appear in any log record.
        for record in caplog.records:
            assert sensitive_token not in record.getMessage(), (
                f"Sensitive value found in log message: {record.getMessage()!r}"
            )
            assert sensitive_token not in str(record.__dict__), (
                f"Sensitive value found in log record extras: {record.__dict__!r}"
            )

    def test_http_exception_non_5xx_does_not_expose_detail(self) -> None:
        secret = "forbidden-student-name"
        client = _make_client_with_route(StarletteHTTPException(status_code=404, detail=secret))

        resp = client.get("/test-error")

        assert resp.status_code == 404
        body = resp.json()
        assert body["error"]["message"] == "Resource not found."
        assert secret not in resp.text
