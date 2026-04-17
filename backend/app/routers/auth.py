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
    ResendVerificationRequest,
    SignupRequest,
    SignupResponse,
    VerifyEmailResponse,
)
from app.services.auth import (
    create_user,
    generate_verification_token,
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
    """Extract the client IP from the direct connection (not X-Forwarded-For)."""
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
