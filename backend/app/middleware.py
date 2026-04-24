"""Custom Starlette middleware for the Rubric Grading Engine.

SecurityHeadersMiddleware
    Adds mandatory security response headers to every HTTP response,
    regardless of the route.  Follows the header set documented in
    ``docs/architecture/security.md#6-api-security``.  Note: Content-Security-
    Policy is intentionally omitted here — it is applied per-page by Next.js
    and would conflict if also set on the backend API.

RateLimitMiddleware
    Enforces per-IP request limits on the auth endpoints (login, signup,
    refresh) using Redis INCR / EXPIRE counters.  A 429 JSON response is
    returned immediately when the limit is exceeded — the route handler is
    never called.

    The public contact/DPA form endpoints are intentionally **excluded** from
    this middleware.  Those routes already enforce their own Redis rate limits
    inside ``app.services.contact`` and ``app.services.dpa_request`` using
    ``request.client.host`` directly.  Adding a second middleware-level counter
    would create duplicate keys and, more importantly, inconsistent IP keying
    when running behind a trusted proxy (the middleware may use CF/XFF while
    the service layer always uses the direct TCP address).
"""

from __future__ import annotations

import ipaddress
import logging
import uuid
from collections.abc import Awaitable, Callable

from redis.asyncio import Redis
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Correlation ID
# ---------------------------------------------------------------------------


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """Generate and propagate a correlation ID for every HTTP request.

    - Reads ``X-Correlation-Id`` from the incoming request if present;
      falls back to a freshly generated UUID4.
    - Stores the ID on ``request.state.correlation_id`` for downstream
      route handlers and services.
    - Sets ``correlation_id_var`` (from ``app.logging_config``) so that all
      log lines emitted during the request carry the same ID.
    - Echoes the ID back in the ``X-Correlation-Id`` response header so that
      clients and log aggregators can correlate request logs with responses.
    """

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        from app.logging_config import correlation_id_var  # noqa: PLC0415

        raw_id = request.headers.get("X-Correlation-Id", "")
        # Accept client-supplied IDs only when they are valid UUID4 strings.
        # Reject anything else to prevent log injection or log bloat.
        if raw_id:
            try:
                parsed = uuid.UUID(raw_id)
            except ValueError:
                correlation_id = str(uuid.uuid4())
            else:
                if parsed.version == 4 and str(parsed) == raw_id.lower():
                    correlation_id = str(parsed)
                else:
                    correlation_id = str(uuid.uuid4())
        else:
            correlation_id = str(uuid.uuid4())
        request.state.correlation_id = correlation_id
        token = correlation_id_var.set(correlation_id)
        try:
            response = await call_next(request)
        finally:
            correlation_id_var.reset(token)

        response.headers["X-Correlation-Id"] = correlation_id
        return response


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
#
# NOTE: the contact endpoints (/api/v1/contact/inquiry and
# /api/v1/contact/dpa-request) intentionally do NOT appear here.  Both
# services (app.services.contact and app.services.dpa_request) already
# enforce their own Redis rate-limit counters using request.client.host
# directly.  Adding a second middleware-level counter would create duplicate
# keys and, more importantly, inconsistent IP keying between the two layers
# (middleware might use CF/XFF while the service layer always uses the direct
# TCP address).  Rate limiting for those routes is owned by the service layer.
_RATE_LIMIT_RULES: list[tuple[str, str, int, int]] = [
    # Login: 10 attempts per IP per 15 minutes
    ("POST", "/api/v1/auth/login", 10, 900),
    # Refresh: 30 attempts per IP per hour
    ("POST", "/api/v1/auth/refresh", 30, 3600),
    # Signup: 5 attempts per IP per hour
    ("POST", "/api/v1/auth/signup", 5, 3600),
]


def _get_client_ip(request: Request) -> str:
    """Return the best-effort client IP for rate-limit keying.

    When ``settings.trust_proxy_headers`` is ``True`` (production, behind
    Cloudflare or another trusted reverse proxy), the real visitor IP is read
    from ``CF-Connecting-IP`` first, then ``X-Forwarded-For``.  When the
    setting is ``False`` (default, development), the direct TCP connection
    address is used to prevent trivial bypasses via crafted headers.
    """
    from app.config import settings

    if settings.trust_proxy_headers:
        for raw in (
            request.headers.get("CF-Connecting-IP", ""),
            request.headers.get("X-Forwarded-For", "").split(",")[0],
        ):
            candidate = raw.strip()
            if candidate:
                try:
                    # Validate that the header value is a real IP address.
                    # This prevents untrusted/crafted header values from
                    # producing unbounded Redis key cardinality or very large
                    # keys.  An invalid value falls through to the TCP address.
                    ipaddress.ip_address(candidate)
                    return candidate
                except ValueError:
                    logger.warning(
                        "Invalid IP in proxy header — falling back to TCP address",
                        extra={"raw_value_length": len(candidate)},
                    )
    if request.client:
        return request.client.host
    return "unknown"


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Per-IP rate limiting for sensitive public endpoints.

    Uses Redis INCR + EXPIRE counters.  The Redis client is injected at
    construction time (created and owned by the caller — see
    ``app.main._register_middleware``) so that its lifecycle (including
    graceful ``aclose()`` on shutdown) can be managed via the app lifespan
    handler.

    When Redis is unavailable the middleware **fails open** (the request is
    allowed through) to avoid taking down authentication for all users.  The
    failure is logged at ERROR level so on-call staff can investigate.
    """

    def __init__(self, app: object, redis_client: Redis[str]) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self._redis: Redis[str] = redis_client

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
            except Exception as exc:
                # If Redis is unavailable, fail open so auth still works.
                logger.error(
                    "Rate limit check failed — Redis unavailable; allowing request",
                    extra={
                        "path": path,
                        "method": method,
                        "error_type": type(exc).__name__,
                    },
                )

            break  # Each request matches at most one rule (exact method + path).

        return await call_next(request)
