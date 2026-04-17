"""Auth service — account creation and email verification.

Business logic for the teacher sign-up flow:

* ``create_user``          — validate email uniqueness, bcrypt-hash password,
                             persist account, and write audit log. The caller
                             is responsible for generating the verification
                             token and enqueueing the verification email.
* ``generate_verification_token`` / ``verify_email`` /
                             ``consume_verification_token`` — HMAC-backed,
                             single-use, 24 h TTL tokens stored in Redis.
* ``resend_verification``  — rate-limited (max 3/h per email) re-send.

No student PII is collected or processed here.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import uuid
from typing import TYPE_CHECKING

import bcrypt
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.exceptions import ConflictError, RateLimitError, ValidationError

if TYPE_CHECKING:
    from app.models.user import User

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Rate-limit constants
# ---------------------------------------------------------------------------

_SIGNUP_RATE_LIMIT_MAX = 5
_SIGNUP_RATE_LIMIT_WINDOW = 3600  # 1 hour

_RESEND_RATE_LIMIT_MAX = 3
_RESEND_RATE_LIMIT_WINDOW = 3600  # 1 hour


# ---------------------------------------------------------------------------
# Redis key helpers
# ---------------------------------------------------------------------------


def _signup_rate_limit_key(ip: str) -> str:
    return f"auth:signup:ratelimit:{ip}"


def _resend_rate_limit_key(email: str) -> str:
    # Hash the email to avoid leaking it via Redis key enumeration.
    return f"auth:resend:ratelimit:{hashlib.sha256(email.lower().encode()).hexdigest()}"


def _verify_token_redis_key(hmac_tag: str) -> str:
    return f"auth:email:verify:{hmac_tag}"


# ---------------------------------------------------------------------------
# Rate limiting helpers
# ---------------------------------------------------------------------------


async def _check_rate_limit(
    redis_client: Redis,  # type: ignore[type-arg]
    key: str,
    max_requests: int,
    window_seconds: int,
    error_message: str,
) -> None:
    """Increment an IP/email counter; raise RateLimitError when exceeded."""
    current: int = await redis_client.incr(key)
    if current == 1:
        await redis_client.expire(key, window_seconds)
    if current > max_requests:
        raise RateLimitError(error_message)


# ---------------------------------------------------------------------------
# HMAC verification token helpers
# ---------------------------------------------------------------------------


def generate_verification_token(hmac_secret: str) -> tuple[str, str]:
    """Generate a single-use verification token.

    Returns:
        (raw_token, hmac_tag) where *raw_token* is sent to the user and
        *hmac_tag* is used as the Redis key suffix.
    """
    raw_token = secrets.token_urlsafe(32)
    hmac_tag = hmac.new(
        key=hmac_secret.encode(),
        msg=raw_token.encode(),
        digestmod=hashlib.sha256,
    ).hexdigest()
    return raw_token, hmac_tag


def _compute_hmac_tag(hmac_secret: str, raw_token: str) -> str:
    return hmac.new(
        key=hmac_secret.encode(),
        msg=raw_token.encode(),
        digestmod=hashlib.sha256,
    ).hexdigest()


async def store_verification_token(
    redis_client: Redis,  # type: ignore[type-arg]
    hmac_tag: str,
    user_id: uuid.UUID,
    ttl_seconds: int,
) -> None:
    """Store the HMAC tag → user_id mapping with TTL in Redis."""
    await redis_client.set(
        _verify_token_redis_key(hmac_tag),
        str(user_id),
        ex=ttl_seconds,
    )


async def consume_verification_token(
    redis_client: Redis,  # type: ignore[type-arg]
    hmac_secret: str,
    raw_token: str,
) -> uuid.UUID | None:
    """Validate an HMAC tag and consume the single-use Redis entry.

    Returns the ``user_id`` if the token is valid and unexpired, or
    ``None`` if it is invalid, expired, or already used.
    """
    hmac_tag = _compute_hmac_tag(hmac_secret, raw_token)
    key = _verify_token_redis_key(hmac_tag)

    # Atomic get-and-delete so two concurrent requests cannot both succeed.
    value = await redis_client.getdel(key)
    if value is None:
        return None
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Public service functions
# ---------------------------------------------------------------------------


async def create_user(
    db: AsyncSession,
    redis_client: Redis,  # type: ignore[type-arg]
    email: str,
    password: str,
    first_name: str,
    last_name: str,
    school_name: str,
    submitter_ip: str | None,
) -> User:
    """Create a new (unverified) teacher account.

    Steps:
    1. Enforce per-IP sign-up rate limit (5/h).
    2. Check email uniqueness — raise ConflictError on duplicate.
    3. Hash password with bcrypt.
    4. Persist the User row.
    5. Write ``teacher_account_created`` audit log entry.

    The caller is responsible for generating the verification token and
    enqueueing the verification email Celery task.

    Args:
        db: Async database session.
        redis_client: Redis client (rate limiting).  # type: ignore[type-arg]
        email: Teacher's email address (already validated).
        password: Plain-text password (will be bcrypt-hashed here).
        first_name: Teacher's first name.
        last_name: Teacher's last name.
        school_name: School or organisation name.
        submitter_ip: Client IP (None in tests without a real request).

    Returns:
        The newly created ``User`` ORM instance.

    Raises:
        RateLimitError: IP has exceeded sign-up rate limit.
        ConflictError: Email is already registered.
    """
    from app.models.audit_log import AuditLog
    from app.models.user import User, UserRole

    # 1. Rate limit
    if submitter_ip:
        await _check_rate_limit(
            redis_client,
            _signup_rate_limit_key(submitter_ip),
            _SIGNUP_RATE_LIMIT_MAX,
            _SIGNUP_RATE_LIMIT_WINDOW,
            "Too many sign-up attempts from this IP. Please try again later.",
        )

    # 2. Email uniqueness
    existing = await db.execute(select(User.id).where(User.email == email.lower()))
    if existing.scalar_one_or_none() is not None:
        raise ConflictError("An account with this email already exists.")

    # 3. Hash password — CPU-bound; run in a thread to avoid blocking the event loop.
    hashed = await run_in_threadpool(
        lambda: bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    )

    # 4. Persist user
    new_user = User(
        email=email.lower(),
        hashed_password=hashed,
        first_name=first_name,
        last_name=last_name,
        school_name=school_name,
        role=UserRole.teacher,
        email_verified=False,
    )
    db.add(new_user)
    await db.flush()  # populate new_user.id without committing yet

    # 5. Audit log
    audit = AuditLog(
        teacher_id=None,  # account not yet authenticated
        entity_type="user",
        entity_id=new_user.id,
        action="teacher_account_created",
        after_value={"email_domain": email.split("@")[-1]},
        ip_address=submitter_ip,
    )
    db.add(audit)
    await db.commit()
    await db.refresh(new_user)

    logger.info(
        "Teacher account created",
        extra={"user_id": str(new_user.id)},
    )
    return new_user


async def verify_email(
    db: AsyncSession,
    redis_client: Redis,  # type: ignore[type-arg]
    raw_token: str,
) -> User:
    """Mark a teacher's email as verified by consuming the single-use token.

    The token is consumed atomically from Redis on first use (``GETDEL``).
    A second click on the same link will return ``None`` from Redis and raise
    ``ValidationError`` — the endpoint is **not** idempotent for subsequent
    requests after the token has been consumed.  Callers should surface a
    "resend" link when 422 is returned so users can obtain a fresh token.

    Args:
        db: Async database session.
        redis_client: Redis client.  # type: ignore[type-arg]
        raw_token: The raw token sent to the user's email address.

    Returns:
        The updated ``User`` ORM instance.

    Raises:
        ValidationError: Token is invalid, expired, or already used.
    """
    from app.config import settings
    from app.models.user import User

    user_id = await consume_verification_token(
        redis_client, settings.email_verification_hmac_secret, raw_token
    )
    if user_id is None:
        raise ValidationError(
            "Verification link is invalid or has expired. Please request a new one.",
            field="token",
        )

    result = await db.execute(select(User).where(User.id == user_id))
    db_user = result.scalar_one_or_none()
    if db_user is None:
        raise ValidationError(
            "Verification link is invalid or has expired. Please request a new one.",
            field="token",
        )

    if db_user.email_verified:
        # User was verified by another means (e.g., admin action); treat as success.
        return db_user

    db_user.email_verified = True
    await db.commit()
    await db.refresh(db_user)

    logger.info(
        "Teacher email verified",
        extra={"user_id": str(db_user.id)},
    )
    return db_user


async def resend_verification(
    db: AsyncSession,
    redis_client: Redis,  # type: ignore[type-arg]
    email: str,
    submitter_ip: str | None,
) -> User | None:
    """Re-queue a verification email for an unverified account.

    Rate limited to 3 resends per hour per email address.

    Returns:
        The ``User`` instance (caller enqueues the task) or ``None`` if the
        email is not registered — we return None silently to avoid confirming
        whether an account exists.

    Raises:
        RateLimitError: Per-email resend limit exceeded.
    """
    from app.models.user import User

    # Rate limit by email (hashed)
    await _check_rate_limit(
        redis_client,
        _resend_rate_limit_key(email),
        _RESEND_RATE_LIMIT_MAX,
        _RESEND_RATE_LIMIT_WINDOW,
        "Too many resend requests for this email. Please try again later.",
    )

    result = await db.execute(select(User).where(User.email == email.lower()))
    db_user = result.scalar_one_or_none()

    # Always return silently when the email is not found or already verified,
    # to avoid confirming account existence to an attacker.
    if db_user is None or db_user.email_verified:
        return None

    logger.info(
        "Verification email resend requested",
        extra={"user_id": str(db_user.id)},
    )
    return db_user
