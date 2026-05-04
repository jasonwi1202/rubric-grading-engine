"""Unit tests for the internal test-only router.

Tests cover:
- Router is NOT registered by default (EXPORT_TASK_FORCE_FAIL=false → 404).
- Router IS registered when EXPORT_TASK_FORCE_FAIL=true.
- POST /api/v1/internal/export-test-controls/arm-failure:
    - 401 when auth dependency raises HTTPException(401).
    - 403 when authenticated teacher does not own the assignment.
    - 404 when assignment does not exist.
    - 200 and sets per-assignment Redis key when authenticated + owner.
    - UUID is normalised (uppercase/brace input → canonical lowercase key).
- DELETE /api/v1/internal/export-test-controls/arm-failure:
    - 401 when auth dependency raises HTTPException(401).
    - 403 when authenticated teacher does not own the assignment.
    - 200 and clears per-assignment Redis key when authenticated + owner.
- The per-assignment key helper produces expected key format.

No real Redis, no real PostgreSQL, no student PII.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi import HTTPException as FastAPIHTTPException
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from app.db.session import get_db
from app.dependencies import get_current_teacher
from app.exceptions import ForbiddenError, NotFoundError
from app.tasks.export import _export_force_fail_once_key

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_teacher() -> MagicMock:
    teacher = MagicMock()
    teacher.id = uuid.uuid4()
    teacher.email = "teacher@school.edu"
    teacher.email_verified = True
    return teacher


def _make_redis_mock() -> AsyncMock:
    redis = AsyncMock()
    redis.set = AsyncMock()
    redis.delete = AsyncMock()
    redis.aclose = AsyncMock()
    return redis


async def _async_gen(value: object):  # type: ignore[return]
    """Async generator that yields a single value (for mocking FastAPI deps)."""
    yield value


def _build_internal_app(
    teacher: MagicMock | None = None,
    redis_mock: AsyncMock | None = None,
    auth_raises: FastAPIHTTPException | None = None,
) -> FastAPI:
    """Build a minimal FastAPI app with only the internal router mounted.

    auth_raises — if set, ``get_current_teacher`` raises this exception.
    redis_mock — if set, ``_get_redis`` returns this mock instead of
                 connecting to a real Redis server.

    Domain exceptions (NotFoundError, ForbiddenError) are registered as
    exception handlers so tests can assert the correct HTTP status codes.
    """
    from app.routers.internal import _get_redis
    from app.routers.internal import router as internal_router

    app = FastAPI()
    app.include_router(internal_router, prefix="/api/v1")

    # Register domain exception handlers so NotFoundError/ForbiddenError
    # map to 404/403 (mirrors what app.main does in production).
    @app.exception_handler(NotFoundError)
    async def _not_found(request, exc: NotFoundError) -> JSONResponse:  # type: ignore[misc]
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(ForbiddenError)
    async def _forbidden(request, exc: ForbiddenError) -> JSONResponse:  # type: ignore[misc]
        return JSONResponse(status_code=403, content={"detail": str(exc)})

    if auth_raises is not None:
        exc = auth_raises  # capture for closure

        def _raise() -> None:
            raise exc

        app.dependency_overrides[get_current_teacher] = _raise  # type: ignore[attr-defined]
    else:
        _teacher = teacher or _make_teacher()
        app.dependency_overrides[get_current_teacher] = lambda: _teacher  # type: ignore[attr-defined]

    if redis_mock is not None:
        _rm = redis_mock  # capture for closure

        async def _fake_redis():  # type: ignore[return]
            yield _rm

        app.dependency_overrides[_get_redis] = _fake_redis  # type: ignore[attr-defined]

    # Provide a no-op DB session so get_db does not try to connect.
    mock_db = MagicMock()
    mock_db.commit = AsyncMock()

    async def _mock_get_db():  # type: ignore[return]
        yield mock_db

    app.dependency_overrides[get_db] = _mock_get_db  # type: ignore[attr-defined]

    return app


def _delete_with_json(client: TestClient, url: str, body: dict) -> object:
    """Send a DELETE request with a JSON body (TestClient.delete has no json= kwarg)."""
    return client.request("DELETE", url, json=body)


# ---------------------------------------------------------------------------
# Key helper
# ---------------------------------------------------------------------------


class TestExportForceFailOnceKey:
    def test_key_includes_prefix(self) -> None:
        aid = str(uuid.uuid4())
        key = _export_force_fail_once_key(aid)
        assert key.startswith("export:force_fail_once:")

    def test_key_includes_assignment_id(self) -> None:
        aid = str(uuid.uuid4())
        key = _export_force_fail_once_key(aid)
        assert aid in key

    def test_different_assignments_produce_different_keys(self) -> None:
        key_a = _export_force_fail_once_key(str(uuid.uuid4()))
        key_b = _export_force_fail_once_key(str(uuid.uuid4()))
        assert key_a != key_b


# ---------------------------------------------------------------------------
# Router registration guard
# ---------------------------------------------------------------------------


class TestRouterRegistration:
    def test_internal_routes_return_404_when_flag_disabled(self) -> None:
        """When EXPORT_TASK_FORCE_FAIL=false the internal router is not included."""
        from app.main import create_app

        app = create_app()
        client = TestClient(app, raise_server_exceptions=False)

        assignment_id = str(uuid.uuid4())
        resp = client.post(
            "/api/v1/internal/export-test-controls/arm-failure",
            json={"assignment_id": assignment_id},
        )
        assert resp.status_code == 404, (
            f"Expected 404 when flag is disabled, got {resp.status_code}"
        )

    def test_internal_routes_accessible_when_router_mounted(self) -> None:
        """The internal router exposes ARM/DISARM endpoints when mounted."""
        redis_mock = _make_redis_mock()
        assignment_id = str(uuid.uuid4())

        app = _build_internal_app(redis_mock=redis_mock)
        with patch("app.routers.internal.get_assignment", new_callable=AsyncMock) as mock_ga:
            mock_ga.return_value = MagicMock()
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.post(
                "/api/v1/internal/export-test-controls/arm-failure",
                json={"assignment_id": assignment_id},
            )
        # 200 confirms the router is mounted and endpoints are reachable.
        assert resp.status_code == 200, (
            f"Expected 200 when router is mounted, got {resp.status_code}: {resp.text}"
        )


# ---------------------------------------------------------------------------
# Authentication guard
# ---------------------------------------------------------------------------


class TestAuthenticationGuard:
    def test_arm_failure_requires_auth(self) -> None:
        """POST without auth returns 401 when get_current_teacher raises."""
        redis_mock = _make_redis_mock()
        assignment_id = str(uuid.uuid4())

        app = _build_internal_app(
            redis_mock=redis_mock,
            auth_raises=FastAPIHTTPException(status_code=401, detail="Missing bearer token"),
        )
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post(
            "/api/v1/internal/export-test-controls/arm-failure",
            json={"assignment_id": assignment_id},
        )
        assert resp.status_code == 401, (
            f"Expected 401 for unauthenticated request, got {resp.status_code}"
        )

    def test_disarm_failure_requires_auth(self) -> None:
        """DELETE without auth returns 401 when get_current_teacher raises."""
        redis_mock = _make_redis_mock()
        assignment_id = str(uuid.uuid4())

        app = _build_internal_app(
            redis_mock=redis_mock,
            auth_raises=FastAPIHTTPException(status_code=401, detail="Missing bearer token"),
        )
        client = TestClient(app, raise_server_exceptions=False)
        resp = _delete_with_json(
            client,
            "/api/v1/internal/export-test-controls/arm-failure",
            {"assignment_id": assignment_id},
        )
        assert resp.status_code == 401, (
            f"Expected 401 for unauthenticated request, got {resp.status_code}"
        )


# ---------------------------------------------------------------------------
# Ownership guard
# ---------------------------------------------------------------------------


class TestOwnershipGuard:
    def test_arm_returns_403_for_wrong_teacher(self) -> None:
        """POST returns 403 when the authenticated teacher does not own the assignment."""
        redis_mock = _make_redis_mock()
        assignment_id = str(uuid.uuid4())

        app = _build_internal_app(redis_mock=redis_mock)
        with patch(
            "app.routers.internal.get_assignment",
            new_callable=AsyncMock,
            side_effect=ForbiddenError("You do not have access to this assignment."),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.post(
                "/api/v1/internal/export-test-controls/arm-failure",
                json={"assignment_id": assignment_id},
            )

        assert resp.status_code == 403, (
            f"Expected 403 for cross-tenant arm attempt, got {resp.status_code}"
        )
        # Redis must NOT have been written.
        redis_mock.set.assert_not_awaited()

    def test_arm_returns_404_when_assignment_missing(self) -> None:
        """POST returns 404 when the assignment does not exist."""
        redis_mock = _make_redis_mock()
        assignment_id = str(uuid.uuid4())

        app = _build_internal_app(redis_mock=redis_mock)
        with patch(
            "app.routers.internal.get_assignment",
            new_callable=AsyncMock,
            side_effect=NotFoundError("Assignment not found."),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.post(
                "/api/v1/internal/export-test-controls/arm-failure",
                json={"assignment_id": assignment_id},
            )

        assert resp.status_code == 404, (
            f"Expected 404 for missing assignment, got {resp.status_code}"
        )
        redis_mock.set.assert_not_awaited()

    def test_disarm_returns_403_for_wrong_teacher(self) -> None:
        """DELETE returns 403 when the authenticated teacher does not own the assignment."""
        redis_mock = _make_redis_mock()
        assignment_id = str(uuid.uuid4())

        app = _build_internal_app(redis_mock=redis_mock)
        with patch(
            "app.routers.internal.get_assignment",
            new_callable=AsyncMock,
            side_effect=ForbiddenError("You do not have access to this assignment."),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            resp = _delete_with_json(
                client,
                "/api/v1/internal/export-test-controls/arm-failure",
                {"assignment_id": assignment_id},
            )

        assert resp.status_code == 403, (
            f"Expected 403 for cross-tenant disarm attempt, got {resp.status_code}"
        )
        redis_mock.delete.assert_not_awaited()


# ---------------------------------------------------------------------------
# ARM endpoint
# ---------------------------------------------------------------------------


class TestArmExportFailure:
    def test_arm_sets_per_assignment_redis_key(self) -> None:
        """POST /arm-failure sets a Redis key scoped to the assignment_id."""
        redis_mock = _make_redis_mock()
        assignment_id = str(uuid.uuid4())

        app = _build_internal_app(redis_mock=redis_mock)
        with patch("app.routers.internal.get_assignment", new_callable=AsyncMock) as mock_ga:
            mock_ga.return_value = MagicMock()
            client = TestClient(app)
            resp = client.post(
                "/api/v1/internal/export-test-controls/arm-failure",
                json={"assignment_id": assignment_id},
            )

        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        body = resp.json()
        assert body["data"]["armed"] is True
        assert body["data"]["assignment_id"] == assignment_id

        expected_key = _export_force_fail_once_key(assignment_id)
        redis_mock.set.assert_awaited_once_with(expected_key, "1", ex=300)

    def test_arm_response_shape(self) -> None:
        """POST /arm-failure response has the expected envelope shape."""
        redis_mock = _make_redis_mock()
        assignment_id = str(uuid.uuid4())

        app = _build_internal_app(redis_mock=redis_mock)
        with patch("app.routers.internal.get_assignment", new_callable=AsyncMock) as mock_ga:
            mock_ga.return_value = MagicMock()
            client = TestClient(app)
            resp = client.post(
                "/api/v1/internal/export-test-controls/arm-failure",
                json={"assignment_id": assignment_id},
            )

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert "armed" in data
        assert "assignment_id" in data

    def test_arm_normalises_uuid(self) -> None:
        """POST normalises the UUID to lowercase hyphenated form in the Redis key."""
        redis_mock = _make_redis_mock()
        raw_id = uuid.uuid4()
        # Send uppercase UUID — FastAPI parses as uuid.UUID and str() canonicalises it.
        uppercase_id = str(raw_id).upper()
        canonical_id = str(raw_id)  # lowercase hyphenated

        app = _build_internal_app(redis_mock=redis_mock)
        with patch("app.routers.internal.get_assignment", new_callable=AsyncMock) as mock_ga:
            mock_ga.return_value = MagicMock()
            client = TestClient(app)
            resp = client.post(
                "/api/v1/internal/export-test-controls/arm-failure",
                json={"assignment_id": uppercase_id},
            )

        assert resp.status_code == 200
        # Response contains canonical (lowercase) form.
        assert resp.json()["data"]["assignment_id"] == canonical_id
        # Redis key uses canonical form — matches what _run_export produces.
        expected_key = _export_force_fail_once_key(canonical_id)
        redis_mock.set.assert_awaited_once_with(expected_key, "1", ex=300)


# ---------------------------------------------------------------------------
# DISARM endpoint
# ---------------------------------------------------------------------------


class TestDisarmExportFailure:
    def test_disarm_deletes_per_assignment_redis_key(self) -> None:
        """DELETE /arm-failure deletes the per-assignment Redis key."""
        redis_mock = _make_redis_mock()
        assignment_id = str(uuid.uuid4())

        app = _build_internal_app(redis_mock=redis_mock)
        with patch("app.routers.internal.get_assignment", new_callable=AsyncMock) as mock_ga:
            mock_ga.return_value = MagicMock()
            client = TestClient(app)
            resp = _delete_with_json(
                client,
                "/api/v1/internal/export-test-controls/arm-failure",
                {"assignment_id": assignment_id},
            )

        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        body = resp.json()
        assert body["data"]["armed"] is False
        assert body["data"]["assignment_id"] == assignment_id

        expected_key = _export_force_fail_once_key(assignment_id)
        redis_mock.delete.assert_awaited_once_with(expected_key)

    def test_disarm_response_shape(self) -> None:
        """DELETE /arm-failure response has the expected envelope shape."""
        redis_mock = _make_redis_mock()
        assignment_id = str(uuid.uuid4())

        app = _build_internal_app(redis_mock=redis_mock)
        with patch("app.routers.internal.get_assignment", new_callable=AsyncMock) as mock_ga:
            mock_ga.return_value = MagicMock()
            client = TestClient(app)
            resp = _delete_with_json(
                client,
                "/api/v1/internal/export-test-controls/arm-failure",
                {"assignment_id": assignment_id},
            )

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["armed"] is False
        assert "assignment_id" in data
