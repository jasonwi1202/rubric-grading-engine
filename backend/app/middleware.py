"""Custom Starlette middleware for the Rubric Grading Engine.

SecurityHeadersMiddleware
    Adds mandatory security response headers to every HTTP response,
    regardless of the route.  Follows the header set documented in
    ``docs/architecture/security.md#6-api-security``.

RateLimitMiddleware
    Enforces per-IP request limits on sensitive public endpoints using Redis
    INCR / EXPIRE counters.  Covers the auth endpoints (login, signup,
    refresh) and the public contact/DPA form endpoints.  A 429 JSON response
    is returned immediately when the limit is exceeded — the route handler is
    never called.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Security headers
# ---------------------------------------------------------------------------

_SECURITY_HEADERS: dict[str, str] = {
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    # Modern browsers treat X-XSS-Protection: 1 as a security risk.  Set to
    # 0 to disable the legacy XSS auditor; rely on CSP instead.
    "X-XSS-Protection": "0",
    "Referrer-Policy": "strict-origin-when-cross-origin",
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Inject security response headers on every HTTP response.

    Headers are set unconditionally so that all responses — including
    framework-level 404/405 errors and 429s from the rate-limit layer —
    carry the required headers.
    """

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        response = await call_next(request)
        for header, value in _SECURITY_HEADERS.items():
            response.headers[header] = value
        return response


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------

# Each rule: (http_method, exact_path, max_requests, window_seconds)
# Paths are matched exactly so that only the specified endpoints are covered.
_RATE_LIMIT_RULES: list[tuple[str, str, int, int]] = [
    # Login: 10 attempts per IP per 15 minutes
    ("POST", "/api/v1/auth/login", 10, 900),
    # Refresh: 30 attempts per IP per hour
    ("POST", "/api/v1/auth/refresh", 30, 3600),
    # Signup: 5 attempts per IP per hour
    ("POST", "/api/v1/auth/signup", 5, 3600),
    # Contact inquiry: 5 per IP per hour
    ("POST", "/api/v1/contact/inquiry", 5, 3600),
    # DPA request: 3 per IP per hour
    ("POST", "/api/v1/contact/dpa-request", 3, 3600),
]


def _get_client_ip(request: Request) -> str:
    """Return the best-effort client IP for rate-limit keying.

    For public unauthenticated endpoints the direct TCP address is always
    used to prevent trivial bypasses via crafted ``X-Forwarded-For`` headers.
    Middleware-level rate limiting runs before the route handler, so the
    ``trust_proxy_headers`` setting from ``app.config`` is intentionally NOT
    consulted here.
    """
    if request.client:
        return request.client.host
    return "unknown"


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Per-IP rate limiting for sensitive public endpoints.

    Uses Redis INCR + EXPIRE counters.  A single async Redis client is
    created per middleware instance (not per request) using the connection-
    pool backed client from ``redis-py``.

    When Redis is unavailable the middleware **fails open** (the request is
    allowed through) to avoid taking down authentication for all users.  The
    failure is logged at ERROR level so on-call staff can investigate.
    """

    def __init__(self, app: object, redis_url: str) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        from redis.asyncio import Redis

        self._redis: Redis = Redis.from_url(redis_url, decode_responses=True)  # type: ignore[type-arg]

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        method = request.method
        path = request.url.path

        for rule_method, rule_path, max_requests, window_seconds in _RATE_LIMIT_RULES:
            if method != rule_method or path != rule_path:
                continue

            client_ip = _get_client_ip(request)
            key = f"ratelimit:{rule_method}:{rule_path}:{client_ip}"

            try:
                current: int = await self._redis.incr(key)
                if current == 1:
                    await self._redis.expire(key, window_seconds)
                if current > max_requests:
                    return JSONResponse(
                        status_code=429,
                        content={
                            "error": {
                                "code": "RATE_LIMITED",
                                "message": "Too many requests. Please try again later.",
                                "field": None,
                            }
                        },
                    )
            except Exception:
                # If Redis is unavailable, fail open so auth still works.
                logger.error(
                    "Rate limit check failed — Redis unavailable; allowing request",
                    extra={"path": path, "method": method},
                )

            break  # Each request matches at most one rule (exact method + path).

        return await call_next(request)
