"""Auth service — account creation, email verification, and session tokens.

Business logic for the teacher auth flow:

* ``create_user``          — validate email uniqueness, bcrypt-hash password,
                             persist account, and write audit log. The caller
                             is responsible for generating the verification
                             token and enqueueing the verification email.
* ``generate_verification_token`` / ``verify_email`` /
                             ``consume_verification_token`` — HMAC-backed,
                             single-use, 24 h TTL tokens stored in Redis.
* ``resend_verification``  — rate-limited (max 3/h per email) re-send.
* ``login_user``           — validate credentials, issue JWT + refresh token.
* ``refresh_access_token`` — consume a refresh token, issue a new pair.
* ``logout_user``          — invalidate a refresh token in Redis.

No student PII is collected or processed here.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import uuid
from collections.abc import Awaitable
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Protocol

import bcrypt
import jwt
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.exceptions import (
    ConflictError,
    RateLimitError,
    RefreshTokenInvalidError,
    UnauthorizedError,
    ValidationError,
)

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

_TRIAL_DURATION_DAYS = 30


class _ScalarOneOrNoneResult[T](Protocol):
    """Protocol for SQLAlchemy-like result objects used by this module."""

    def scalar_one_or_none(self) -> T | None | Awaitable[T | None]: ...


async def _scalar_one_or_none[T](result: _ScalarOneOrNoneResult[T]) -> T | None:
    """Return ``scalar_one_or_none()`` from real or mocked SQLAlchemy results.

    SQLAlchemy's ``Result.scalar_one_or_none()`` is synchronous, but many unit
    tests model the result object with ``AsyncMock``. In that case the method
    returns an awaitable. Support both shapes so service logic stays aligned
    with production behavior while remaining compatible with the existing tests.
    """
    value = result.scalar_one_or_none()
    if isinstance(value, Awaitable):
        return await value
    return value


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


def _refresh_token_redis_key(token: str) -> str:
    return f"auth:refresh:{token}"


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
    from app.config import settings

    if not settings.rate_limit_enabled:
        return

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
    existing_id: uuid.UUID | None = await _scalar_one_or_none(existing)
    if existing_id is not None:
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
    try:
        await db.flush()  # populate new_user.id without committing yet
    except IntegrityError:
        # A concurrent sign-up with the same email hit the DB unique constraint.
        await db.rollback()
        raise ConflictError("An account with this email already exists.") from None

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
    db_user: User | None = await _scalar_one_or_none(result)
    if db_user is None:
        raise ValidationError(
            "Verification link is invalid or has expired. Please request a new one.",
            field="token",
        )

    if db_user.email_verified:
        # User was verified by another means (e.g., admin action); treat as success.
        # Ensure trial_ends_at is set in case it was missing (e.g., pre-migration rows).
        if db_user.trial_ends_at is None:
            db_user.trial_ends_at = datetime.now(UTC) + timedelta(days=_TRIAL_DURATION_DAYS)
            await db.commit()
            await db.refresh(db_user)
        return db_user

    db_user.email_verified = True
    db_user.trial_ends_at = datetime.now(UTC) + timedelta(days=_TRIAL_DURATION_DAYS)
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
    db_user: User | None = await _scalar_one_or_none(result)

    # Always return silently when the email is not found or already verified,
    # to avoid confirming account existence to an attacker.
    if db_user is None or db_user.email_verified:
        return None

    logger.info(
        "Verification email resend requested",
        extra={"user_id": str(db_user.id)},
    )
    return db_user


# ---------------------------------------------------------------------------
# JWT / session token helpers
# ---------------------------------------------------------------------------


def create_access_token(user_id: uuid.UUID, email: str) -> str:
    """Generate a signed JWT access token for the given teacher.

    The token carries ``sub`` (user UUID string), ``email``, ``iat``, and
    ``exp`` claims.  It is signed with HS256 using ``settings.jwt_secret_key``.
    TTL is ``settings.short_lived_token_ttl_seconds`` (seconds) when set —
    used only in CI E2E to enable deterministic token-expiry testing — or
    ``settings.access_token_expire_minutes`` (minutes, default 15) otherwise.
    """
    from app.config import settings

    now = datetime.now(UTC)
    if settings.short_lived_token_ttl_seconds is not None:
        ttl = timedelta(seconds=settings.short_lived_token_ttl_seconds)
    else:
        ttl = timedelta(minutes=settings.access_token_expire_minutes)
    payload: dict[str, object] = {
        "sub": str(user_id),
        "email": email,
        "type": "access",
        "iat": now,
        "exp": now + ttl,
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict[str, object]:
    """Decode and verify a JWT access token.

    Returns:
        The decoded payload dict.

    Raises:
        ValidationError: Token is malformed, expired, or has an invalid signature.
    """
    from app.config import settings

    try:
        payload: dict[str, object] = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
            options={"verify_exp": True},
        )
    except jwt.ExpiredSignatureError as exc:
        raise ValidationError("Access token has expired.", field="token") from exc
    except jwt.InvalidTokenError as exc:
        raise ValidationError("Access token is invalid.", field="token") from exc
    return payload


def create_refresh_token() -> str:
    """Generate a cryptographically random opaque refresh token string."""
    return secrets.token_urlsafe(48)


async def store_refresh_token(
    redis_client: Redis,  # type: ignore[type-arg]
    refresh_token: str,
    user_id: uuid.UUID,
    ttl_seconds: int,
) -> None:
    """Persist the refresh token -> user_id mapping in Redis with TTL."""
    await redis_client.set(
        _refresh_token_redis_key(refresh_token),
        str(user_id),
        ex=ttl_seconds,
    )


async def consume_refresh_token(
    redis_client: Redis,  # type: ignore[type-arg]
    refresh_token: str,
) -> uuid.UUID | None:
    """Atomically consume a refresh token from Redis.

    Returns:
        The ``user_id`` if the token is valid and unexpired, or ``None``
        if it is invalid, expired, or already used.
    """
    key = _refresh_token_redis_key(refresh_token)
    value: str | None = await redis_client.getdel(key)
    if value is None:
        return None
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


async def delete_refresh_token(
    redis_client: Redis,  # type: ignore[type-arg]
    refresh_token: str,
) -> None:
    """Remove a refresh token from Redis (logout)."""
    await redis_client.delete(_refresh_token_redis_key(refresh_token))


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------


async def login_user(
    db: AsyncSession,
    redis_client: Redis,  # type: ignore[type-arg]
    email: str,
    password: str,
    submitter_ip: str | None = None,
) -> tuple[User, str, str]:
    """Authenticate a teacher and issue a JWT + refresh token pair.

    Steps:
    1. Look up teacher by email.
    2. Verify ``email_verified = True`` -- unverified accounts cannot log in.
    3. Validate the password via bcrypt.
    4. Update ``last_login_at``.
    5. Write audit log entry (login_success or login_failure).
    6. Generate and store refresh token in Redis.
    7. Return (user, access_token, refresh_token).

    Args:
        db: Async database session.
        redis_client: Redis client for refresh token storage.
        email: Teacher's email address.
        password: Plain-text password to verify.
        submitter_ip: Client IP address for audit log.

    Returns:
        Tuple of (User ORM instance, JWT access token string, refresh token string).

    Raises:
        ValidationError: Credentials are invalid or email is not verified.
    """
    from app.config import settings
    from app.models.audit_log import AuditLog
    from app.models.user import User

    result = await db.execute(select(User).where(User.email == email.lower()))
    db_user: User | None = await _scalar_one_or_none(result)

    # Use a generic message to avoid confirming whether the email is registered.
    _invalid_msg = "Invalid email or password."

    if db_user is None:
        # Still write a login_failure audit log so we can detect brute-force
        # attempts; no PII stored -- entity_id is None.
        audit = AuditLog(
            teacher_id=None,
            entity_type="user",
            entity_id=None,
            action="login_failure",
            after_value={"reason": "email_not_found"},
            ip_address=submitter_ip,
        )
        db.add(audit)
        await db.commit()
        raise UnauthorizedError(_invalid_msg)

    if not db_user.email_verified and not settings.allow_unverified_login_in_test:
        audit = AuditLog(
            teacher_id=None,
            entity_type="user",
            entity_id=db_user.id,
            action="login_failure",
            after_value={"reason": "email_not_verified"},
            ip_address=submitter_ip,
        )
        db.add(audit)
        await db.commit()
        raise UnauthorizedError("Please verify your email address before signing in.")

    # Verify password -- CPU-bound; run in a thread to avoid blocking the event loop.
    password_valid: bool = await run_in_threadpool(
        lambda: bcrypt.checkpw(password.encode(), db_user.hashed_password.encode())
    )

    if not password_valid:
        audit = AuditLog(
            teacher_id=None,
            entity_type="user",
            entity_id=db_user.id,
            action="login_failure",
            after_value={"reason": "invalid_password"},
            ip_address=submitter_ip,
        )
        db.add(audit)
        await db.commit()
        raise UnauthorizedError(_invalid_msg)

    # Update last_login_at
    db_user.last_login_at = datetime.now(UTC)

    # Write login_success audit log
    success_audit = AuditLog(
        teacher_id=db_user.id,
        entity_type="user",
        entity_id=db_user.id,
        action="login_success",
        ip_address=submitter_ip,
    )
    db.add(success_audit)
    await db.commit()
    await db.refresh(db_user)

    # Generate tokens
    access_token = create_access_token(db_user.id, db_user.email)
    refresh_token = create_refresh_token()
    await store_refresh_token(
        redis_client,
        refresh_token,
        db_user.id,
        settings.refresh_token_expire_days * 86400,
    )

    logger.info("Teacher login successful", extra={"user_id": str(db_user.id)})
    return db_user, access_token, refresh_token


# ---------------------------------------------------------------------------
# Token refresh
# ---------------------------------------------------------------------------


async def refresh_access_token(
    db: AsyncSession,
    redis_client: Redis,  # type: ignore[type-arg]
    refresh_token: str,
    submitter_ip: str | None = None,
) -> tuple[User, str, str]:
    """Issue a new access token + rotated refresh token.

    The incoming refresh token is consumed atomically; a fresh one is issued.
    Returns (user, new_access_token, new_refresh_token).

    Raises:
        RefreshTokenInvalidError: Refresh token is invalid, expired, or already used.
    """
    from app.config import settings
    from app.models.audit_log import AuditLog
    from app.models.user import User

    user_id = await consume_refresh_token(redis_client, refresh_token)
    if user_id is None:
        raise RefreshTokenInvalidError("Refresh token is invalid or has expired.")

    result = await db.execute(select(User).where(User.id == user_id))
    db_user: User | None = await _scalar_one_or_none(result)
    if db_user is None:
        raise RefreshTokenInvalidError("Refresh token is invalid or has expired.")

    # Keep refresh behavior consistent with login in CI/test mode where
    # unverified-login bypass can be enabled for deterministic E2E runs.
    if not db_user.email_verified and not settings.allow_unverified_login_in_test:
        raise RefreshTokenInvalidError("Refresh token is invalid or has expired.")

    # Write audit log
    audit = AuditLog(
        teacher_id=db_user.id,
        entity_type="user",
        entity_id=db_user.id,
        action="token_refreshed",
        ip_address=submitter_ip,
    )
    db.add(audit)
    await db.commit()

    new_access_token = create_access_token(db_user.id, db_user.email)
    new_refresh_token = create_refresh_token()
    await store_refresh_token(
        redis_client,
        new_refresh_token,
        db_user.id,
        settings.refresh_token_expire_days * 86400,
    )

    logger.info("Access token refreshed", extra={"user_id": str(db_user.id)})
    return db_user, new_access_token, new_refresh_token


# ---------------------------------------------------------------------------
# Logout
# ---------------------------------------------------------------------------


async def logout_user(
    db: AsyncSession,
    redis_client: Redis,  # type: ignore[type-arg]
    refresh_token: str,
    teacher_id: uuid.UUID,
    submitter_ip: str | None = None,
) -> None:
    """Invalidate the refresh token and write an audit log entry.

    Args:
        db: Async database session.
        redis_client: Redis client.
        refresh_token: The refresh token to invalidate.
        teacher_id: The authenticated teacher's UUID (for audit log).
        submitter_ip: Client IP address for audit log.
    """
    from app.models.audit_log import AuditLog

    await delete_refresh_token(redis_client, refresh_token)

    audit = AuditLog(
        teacher_id=teacher_id,
        entity_type="user",
        entity_id=teacher_id,
        action="logout",
        ip_address=submitter_ip,
    )
    db.add(audit)
    await db.commit()
    logger.info("Teacher logged out", extra={"user_id": str(teacher_id)})
