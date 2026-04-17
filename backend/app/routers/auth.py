"""Auth router — sign-up and email verification endpoints.

All endpoints here are **unauthenticated** (public).  They follow the same
patterns as the contact router: thin router, service does the work, Redis
client injected as a FastAPI dependency.

Rate limiting is enforced in the service layer (Redis counters):
  - Sign-up:  max 5 attempts per IP per hour
  - Resend:   max 3 attempts per email per hour

Security notes:
  - Passwords are never logged.
  - The ``resend-verification`` endpoint always returns 202 regardless of
    whether the email is registered, to avoid leaking account existence.
  - HMAC-signed, single-use, 24 h TTL verification tokens (Redis).
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from redis.asyncio import Redis

from app.db.session import AsyncSession, get_db
from app.schemas.auth import (
    LoginRequest,
    LoginResponse,
    RefreshResponse,
    ResendVerificationRequest,
    SignupRequest,
    SignupResponse,
    VerifyEmailResponse,
)
from app.services.auth import (
    create_user,
    generate_verification_token,
    login_user,
    logout_user,
    refresh_access_token,
    resend_verification,
    store_verification_token,
    verify_email,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------


async def _get_redis() -> AsyncGenerator[Redis, None]:  # type: ignore[type-arg]
    """FastAPI dependency that yields an async Redis client."""
    from app.config import settings

    client: Redis = Redis.from_url(settings.redis_url, decode_responses=True)  # type: ignore[type-arg]
    try:
        yield client
    finally:
        await client.aclose()  # type: ignore[attr-defined]


def _get_client_ip(request: Request) -> str | None:
    """Extract the real client IP address.

    When ``settings.trust_proxy_headers`` is ``True`` (i.e. the app is running
    behind a trusted reverse proxy such as Cloudflare), the IP is read from the
    ``CF-Connecting-IP`` header first, then ``X-Forwarded-For``.  In all other
    cases the direct TCP connection address is used to prevent IP spoofing via
    crafted headers.
    """
    from app.config import settings

    if settings.trust_proxy_headers:
        # Cloudflare sets CF-Connecting-IP to the original visitor IP.
        cf_ip = request.headers.get("CF-Connecting-IP")
        if cf_ip:
            return cf_ip.strip()
        # Generic reverse-proxy header — take the leftmost (originating) address.
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()
    if request.client:
        return request.client.host
    return None


# ---------------------------------------------------------------------------
# POST /auth/signup
# ---------------------------------------------------------------------------


@router.post(
    "/signup",
    status_code=201,
    summary="Create a new teacher account",
)
async def signup(
    request: Request,
    payload: SignupRequest,
    db: AsyncSession = Depends(get_db),
    redis_client: Redis = Depends(_get_redis),  # type: ignore[type-arg]
) -> JSONResponse:
    """Create an unverified teacher account and enqueue a verification email.

    - Rate limited: 5 sign-up attempts per IP per hour.
    - Returns 409 if the email is already registered.
    - Password is bcrypt-hashed; the plain-text value is never logged.
    - On success returns 201 with the new account's ``id`` and ``email``.
    """
    from app.config import settings
    from app.tasks.email import send_verification_email

    client_ip = _get_client_ip(request)
    new_user = await create_user(
        db,
        redis_client,
        email=payload.email,
        password=payload.password,
        first_name=payload.first_name,
        last_name=payload.last_name,
        school_name=payload.school_name,
        submitter_ip=client_ip,
    )

    # Generate HMAC-signed verification token and persist in Redis.
    raw_token, hmac_tag = generate_verification_token(settings.email_verification_hmac_secret)
    await store_verification_token(
        redis_client,
        hmac_tag,
        new_user.id,
        settings.verification_token_ttl_seconds,
    )

    # Enqueue verification email asynchronously — fire-and-forget.
    try:
        send_verification_email.delay(
            user_id=str(new_user.id),
            raw_token=raw_token,
        )
    except Exception as exc:
        logger.exception(
            "Failed to enqueue verification email task",
            extra={"user_id": str(new_user.id), "error_type": type(exc).__name__},
        )

    response_data = SignupResponse(
        id=new_user.id,
        email=new_user.email,
        created_at=new_user.created_at,
        message="Account created. Please check your email to verify your address.",
    )
    return JSONResponse(
        status_code=201,
        content={"data": response_data.model_dump(mode="json")},
    )


# ---------------------------------------------------------------------------
# GET /auth/verify-email
# ---------------------------------------------------------------------------


@router.get(
    "/verify-email",
    summary="Verify a teacher's email address via token",
)
async def verify_email_endpoint(
    token: str,
    db: AsyncSession = Depends(get_db),
    redis_client: Redis = Depends(_get_redis),  # type: ignore[type-arg]
) -> JSONResponse:
    """Consume a single-use HMAC-signed verification token and mark the
    account as email-verified.

    - Returns 200 on success.
    - Returns 422 for invalid, expired, or already-used tokens.
    """
    await verify_email(db, redis_client, token)
    response = VerifyEmailResponse(message="Email verified successfully. You can now sign in.")
    return JSONResponse(
        status_code=200,
        content={"data": response.model_dump(mode="json")},
    )


# ---------------------------------------------------------------------------
# POST /auth/resend-verification
# ---------------------------------------------------------------------------


@router.post(
    "/resend-verification",
    status_code=202,
    summary="Resend the email verification link",
)
async def resend_verification_endpoint(
    payload: ResendVerificationRequest,
    db: AsyncSession = Depends(get_db),
    redis_client: Redis = Depends(_get_redis),  # type: ignore[type-arg]
) -> JSONResponse:
    """Re-enqueue a verification email for an unverified account.

    Always returns 202 regardless of whether the email is registered, to
    avoid confirming account existence to an attacker.

    Rate limited to 3 resends per email per hour.
    """
    from app.config import settings
    from app.tasks.email import send_verification_email

    db_user = await resend_verification(db, redis_client, payload.email, submitter_ip=None)

    if db_user is not None:
        raw_token, hmac_tag = generate_verification_token(settings.email_verification_hmac_secret)
        await store_verification_token(
            redis_client,
            hmac_tag,
            db_user.id,
            settings.verification_token_ttl_seconds,
        )
        try:
            send_verification_email.delay(
                user_id=str(db_user.id),
                raw_token=raw_token,
            )
        except Exception as exc:
            logger.exception(
                "Failed to enqueue verification email resend task",
                extra={"user_id": str(db_user.id), "error_type": type(exc).__name__},
            )

    return JSONResponse(
        status_code=202,
        content={
            "data": {
                "message": "If an unverified account exists for that email, a new verification link has been sent."
            }
        },
    )


# ---------------------------------------------------------------------------
# POST /auth/login
# ---------------------------------------------------------------------------

_REFRESH_TOKEN_COOKIE = "refresh_token"
_REFRESH_TOKEN_COOKIE_MAX_AGE = 7 * 86400  # 7 days in seconds


@router.post(
    "/login",
    summary="Authenticate a teacher and issue tokens",
)
async def login_endpoint(
    request: Request,
    payload: LoginRequest,
    db: AsyncSession = Depends(get_db),
    redis_client: Redis = Depends(_get_redis),  # type: ignore[type-arg]
) -> JSONResponse:
    """Validate teacher credentials and issue a JWT access token + refresh token.

    - The JWT access token is returned in the response body (15 min TTL).
    - The refresh token is set as an httpOnly, Secure, SameSite=Strict cookie
      (7 day TTL). It is never exposed in the response body.
    - Returns 422 for invalid credentials or unverified email.
    """
    client_ip = _get_client_ip(request)
    _user, access_token, refresh_token = await login_user(
        db,
        redis_client,
        email=payload.email,
        password=payload.password,
        submitter_ip=client_ip,
    )

    response_data = LoginResponse(access_token=access_token)
    response = JSONResponse(
        status_code=200,
        content={"data": response_data.model_dump(mode="json")},
    )
    response.set_cookie(
        key=_REFRESH_TOKEN_COOKIE,
        value=refresh_token,
        httponly=True,
        secure=True,
        samesite="strict",
        max_age=_REFRESH_TOKEN_COOKIE_MAX_AGE,
        path="/",
    )
    return response


# ---------------------------------------------------------------------------
# POST /auth/refresh
# ---------------------------------------------------------------------------


@router.post(
    "/refresh",
    summary="Exchange a refresh token for a new access token",
)
async def refresh_token_endpoint(
    request: Request,
    db: AsyncSession = Depends(get_db),
    redis_client: Redis = Depends(_get_redis),  # type: ignore[type-arg]
) -> JSONResponse:
    """Consume the httpOnly refresh-token cookie and issue a new access token.

    The refresh token is rotated on every use (old token is invalidated, new
    one is set in a fresh cookie).

    Returns 422 if the cookie is absent or the token is invalid/expired.
    """
    client_ip = _get_client_ip(request)
    incoming_refresh = request.cookies.get(_REFRESH_TOKEN_COOKIE)
    if not incoming_refresh:
        return JSONResponse(
            status_code=401,
            content={
                "error": {
                    "code": "REFRESH_TOKEN_INVALID",
                    "message": "Refresh token is missing or invalid.",
                    "field": None,
                }
            },
        )

    _user, new_access_token, new_refresh_token = await refresh_access_token(
        db,
        redis_client,
        refresh_token=incoming_refresh,
        submitter_ip=client_ip,
    )

    response_data = RefreshResponse(access_token=new_access_token)
    response = JSONResponse(
        status_code=200,
        content={"data": response_data.model_dump(mode="json")},
    )
    response.set_cookie(
        key=_REFRESH_TOKEN_COOKIE,
        value=new_refresh_token,
        httponly=True,
        secure=True,
        samesite="strict",
        max_age=_REFRESH_TOKEN_COOKIE_MAX_AGE,
        path="/",
    )
    return response


# ---------------------------------------------------------------------------
# POST /auth/logout
# ---------------------------------------------------------------------------


@router.post(
    "/logout",
    status_code=204,
    summary="Invalidate the refresh token and clear the session cookie",
)
async def logout_endpoint(
    request: Request,
    db: AsyncSession = Depends(get_db),
    redis_client: Redis = Depends(_get_redis),  # type: ignore[type-arg]
) -> JSONResponse:
    """Invalidate the server-side refresh token and clear the session cookie.

    Returns 204 regardless of whether the cookie was present or valid, so
    that clients can safely call this endpoint multiple times (idempotent
    from the client's perspective).
    """
    from app.dependencies import get_current_teacher_optional

    client_ip = _get_client_ip(request)
    incoming_refresh = request.cookies.get(_REFRESH_TOKEN_COOKIE)

    # Attempt to identify the authenticated teacher for the audit log.
    # If the access token is absent or invalid, teacher_id will be None.
    teacher_id = await get_current_teacher_optional(request, db)

    if incoming_refresh and teacher_id is not None:
        await logout_user(
            db,
            redis_client,
            refresh_token=incoming_refresh,
            teacher_id=teacher_id,
            submitter_ip=client_ip,
        )
    elif incoming_refresh:
        # No valid access token but we have a refresh token -- delete it
        # from Redis so it can't be reused.
        from app.services.auth import delete_refresh_token

        await delete_refresh_token(redis_client, incoming_refresh)

    response = JSONResponse(status_code=204, content=None)
    response.delete_cookie(
        key=_REFRESH_TOKEN_COOKIE,
        path="/",
        httponly=True,
        secure=True,
        samesite="strict",
    )
    return response
