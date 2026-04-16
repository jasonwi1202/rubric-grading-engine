"""Unit tests for the health endpoint and global exception handlers."""

import pytest
from fastapi.testclient import TestClient

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
    def test_health_returns_200(self, client: TestClient) -> None:
        resp = client.get("/api/v1/health")
        assert resp.status_code == 200, f"Got {resp.status_code}"

    def test_health_returns_ok_body(self, client: TestClient) -> None:
        resp = client.get("/api/v1/health")
        assert resp.json() == {"status": "ok"}, f"Got {resp.json()}"


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
