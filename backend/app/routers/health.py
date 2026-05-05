"""Health and readiness routers.

Exposes two unauthenticated probe endpoints:

``GET /api/v1/health`` — **Liveness probe**
    Returns ``"ok"`` when the process is running and can reach all critical
    dependencies (database and Redis).  Returns ``"degraded"`` with HTTP 503
    when any dependency is unreachable.  Railway restarts the container when
    this probe returns 503.

``GET /api/v1/readiness`` — **Readiness probe**
    Returns ``"ready"`` when the service is fully initialised and able to
    handle production traffic.  Returns ``"not_ready"`` with HTTP 503 when
    a dependency is unavailable.  Railway uses this signal during rolling
    deploys to decide when to shift traffic to the new instance — the old
    instance continues serving traffic until the new one is ready.

Both endpoints share the same dependency checks (database ``SELECT 1`` and
Redis ``PING``) and return the same JSON envelope shape so that callers can
always parse the body regardless of HTTP status code.

These endpoints intentionally require **no authentication** so that load
balancers and Railway health-check probes can reach them without credentials.
"""

from __future__ import annotations

import asyncio
import importlib.metadata
import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])

_SERVICE_NAME = "rubric-grading-engine-api"

try:
    _VERSION = importlib.metadata.version("rubric-grading-engine")
except importlib.metadata.PackageNotFoundError:
    _VERSION = "unknown"


async def _check_database() -> bool:
    """Return ``True`` if the database accepts a trivial query, ``False`` otherwise.

    Enforces a 3-second timeout so that a stalled TCP/DNS connection does not
    block the health endpoint indefinitely (which would cause load balancer
    probes to time out rather than receive a 503).
    """
    try:
        import sqlalchemy  # noqa: PLC0415

        from app.db.session import engine  # noqa: PLC0415

        async with asyncio.timeout(3):
            async with engine.connect() as conn:
                await conn.execute(sqlalchemy.text("SELECT 1"))
        return True
    except Exception as exc:
        logger.warning(
            "Health check: database unavailable",
            extra={"error_type": type(exc).__name__},
        )
        return False


async def _check_redis() -> bool:
    """Return ``True`` if Redis responds to PING, ``False`` otherwise."""
    try:
        from redis.asyncio import Redis  # noqa: PLC0415

        from app.config import settings  # noqa: PLC0415

        r = Redis.from_url(
            settings.redis_url,
            socket_connect_timeout=2,
            socket_timeout=2,
            decode_responses=True,
        )
        try:
            await r.ping()
        finally:
            await r.aclose()  # type: ignore[attr-defined]  # redis.asyncio stubs do not expose aclose()
        return True
    except Exception as exc:
        logger.warning(
            "Health check: Redis unavailable",
            extra={"error_type": type(exc).__name__},
        )
        return False


@router.get("/health")
async def health_check() -> JSONResponse:
    """Return service liveness and dependency health status.

    Always returns the same JSON shape so that callers can parse the body
    regardless of HTTP status code.

    Response shape::

        {
          "data": {
            "status": "ok",
            "service": "rubric-grading-engine-api",
            "version": "0.1.0",
            "dependencies": {
              "database": "ok",
              "redis": "ok"
            }
          }
        }

    HTTP 200 — all dependencies healthy.
    HTTP 503 — one or more dependencies unavailable (``status`` is ``"degraded"``).

    No authentication is required — load balancers and Railway health-check
    probes must be able to reach this endpoint without credentials.
    """
    db_ok = await _check_database()
    redis_ok = await _check_redis()
    all_ok = db_ok and redis_ok

    return JSONResponse(
        status_code=200 if all_ok else 503,
        content={
            "data": {
                "status": "ok" if all_ok else "degraded",
                "service": _SERVICE_NAME,
                "version": _VERSION,
                "dependencies": {
                    "database": "ok" if db_ok else "unavailable",
                    "redis": "ok" if redis_ok else "unavailable",
                },
            }
        },
    )


@router.get("/readiness")
async def readiness_check() -> JSONResponse:
    """Return service readiness for traffic during Railway rolling deploys.

    Railway uses this endpoint to decide when to shift production traffic from
    the old container to the newly deployed one.  The new container must return
    HTTP 200 before Railway routes any traffic to it.

    The check is identical to the liveness probe — database ``SELECT 1`` and
    Redis ``PING`` — because both dependencies must be reachable before the
    service can process any request.

    Response shape::

        {
          "data": {
            "status": "ready",
            "service": "rubric-grading-engine-api",
            "version": "0.1.0",
            "dependencies": {
              "database": "ok",
              "redis": "ok"
            }
          }
        }

    HTTP 200 — service is ready to accept traffic.
    HTTP 503 — service is not yet ready (``status`` is ``"not_ready"``).

    No authentication is required.
    """
    db_ok = await _check_database()
    redis_ok = await _check_redis()
    all_ok = db_ok and redis_ok

    return JSONResponse(
        status_code=200 if all_ok else 503,
        content={
            "data": {
                "status": "ready" if all_ok else "not_ready",
                "service": _SERVICE_NAME,
                "version": _VERSION,
                "dependencies": {
                    "database": "ok" if db_ok else "unavailable",
                    "redis": "ok" if redis_ok else "unavailable",
                },
            }
        },
    )
