"""Unit tests for the auth service — account creation, token management,
email verification, and resend-verification.

All tests mock Redis and the database so no external services are required.
No real student PII is used in fixtures.
"""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.exceptions import ConflictError, RateLimitError, ValidationError
from app.services.auth import (
    _compute_hmac_tag,
    _resend_rate_limit_key,
    _signup_rate_limit_key,
    _verify_token_redis_key,
    consume_verification_token,
    create_user,
    generate_verification_token,
    resend_verification,
    verify_email,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_HMAC_SECRET = "b" * 32


def _make_mock_db() -> AsyncMock:
    """Return a minimal AsyncSession mock that handles add/flush/commit/refresh."""
    db = AsyncMock()
    # Fake the execute().scalar_one_or_none() chain
    db.execute = AsyncMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()

    fake_user = MagicMock()
    fake_user.id = uuid.uuid4()
    fake_user.email = "teacher@school.edu"
    fake_user.first_name = "Alex"
    fake_user.last_name = "Smith"
    fake_user.school_name = "Test School"
    fake_user.email_verified = False
    fake_user.created_at = datetime.now(UTC)

    db.refresh = AsyncMock(return_value=fake_user)
    return db, fake_user


def _make_mock_redis(incr_return: int = 1) -> AsyncMock:
    redis = AsyncMock()
    redis.incr = AsyncMock(return_value=incr_return)
    redis.expire = AsyncMock()
    redis.set = AsyncMock()
    redis.getdel = AsyncMock(return_value=None)
    return redis


# ---------------------------------------------------------------------------
# HMAC token helpers
# ---------------------------------------------------------------------------


class TestGenerateVerificationToken:
    def test_returns_raw_token_and_hmac_tag(self) -> None:
        raw_token, hmac_tag = generate_verification_token(_HMAC_SECRET)
        assert isinstance(raw_token, str)
        assert len(raw_token) > 0
        assert isinstance(hmac_tag, str)
        assert len(hmac_tag) == 64  # SHA-256 hex digest

    def test_hmac_tag_matches_expected(self) -> None:
        raw_token, hmac_tag = generate_verification_token(_HMAC_SECRET)
        expected_tag = _compute_hmac_tag(_HMAC_SECRET, raw_token)
        assert hmac_tag == expected_tag

    def test_different_calls_produce_different_tokens(self) -> None:
        t1, _ = generate_verification_token(_HMAC_SECRET)
        t2, _ = generate_verification_token(_HMAC_SECRET)
        assert t1 != t2


class TestConsumeVerificationToken:
    @pytest.mark.asyncio
    async def test_returns_user_id_when_token_valid(self) -> None:
        user_id = uuid.uuid4()
        redis = _make_mock_redis()
        redis.getdel = AsyncMock(return_value=str(user_id))

        raw_token = "some_token"
        result = await consume_verification_token(redis, _HMAC_SECRET, raw_token)
        assert result == user_id

    @pytest.mark.asyncio
    async def test_returns_none_when_token_missing(self) -> None:
        redis = _make_mock_redis()
        redis.getdel = AsyncMock(return_value=None)

        result = await consume_verification_token(redis, _HMAC_SECRET, "expired_token")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_stored_value_invalid_uuid(self) -> None:
        redis = _make_mock_redis()
        redis.getdel = AsyncMock(return_value="not-a-uuid")

        result = await consume_verification_token(redis, _HMAC_SECRET, "some_token")
        assert result is None

    @pytest.mark.asyncio
    async def test_calls_getdel_with_correct_key(self) -> None:
        user_id = uuid.uuid4()
        redis = _make_mock_redis()
        redis.getdel = AsyncMock(return_value=str(user_id))

        raw_token = "my_raw_token"
        await consume_verification_token(redis, _HMAC_SECRET, raw_token)

        expected_tag = _compute_hmac_tag(_HMAC_SECRET, raw_token)
        expected_key = _verify_token_redis_key(expected_tag)
        redis.getdel.assert_awaited_once_with(expected_key)


# ---------------------------------------------------------------------------
# create_user
# ---------------------------------------------------------------------------


class TestCreateUser:
    @pytest.mark.asyncio
    async def test_raises_rate_limit_error_when_ip_limit_exceeded(self) -> None:
        db, _ = _make_mock_db()
        redis = _make_mock_redis(incr_return=6)  # exceeds limit of 5

        with pytest.raises(RateLimitError):
            await create_user(
                db,
                redis,
                email="teacher@school.edu",
                password="Pass1234",
                first_name="Alex",
                last_name="Smith",
                school_name="Test School",
                submitter_ip="1.2.3.4",
            )

    @pytest.mark.asyncio
    async def test_raises_conflict_error_on_duplicate_email(self) -> None:
        db, _ = _make_mock_db()
        redis = _make_mock_redis(incr_return=1)

        # Simulate existing user in DB
        existing_id = uuid.uuid4()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=existing_id)
        db.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(ConflictError):
            await create_user(
                db,
                redis,
                email="taken@school.edu",
                password="Pass1234",
                first_name="Alex",
                last_name="Smith",
                school_name="Test School",
                submitter_ip=None,
            )

    @pytest.mark.asyncio
    async def test_skips_rate_limit_when_no_ip(self) -> None:
        """create_user must NOT call Redis when submitter_ip is None."""
        db, _ = _make_mock_db()
        redis = _make_mock_redis()
        redis.incr = AsyncMock(return_value=99)

        # Let the DB query raise — we only care that Redis was not called.
        db.execute = AsyncMock(side_effect=RuntimeError("db unavailable"))

        with pytest.raises(RuntimeError):
            await create_user(
                db,
                redis,
                email="new@school.edu",
                password="Pass1234",
                first_name="Alex",
                last_name="Smith",
                school_name="Test School",
                submitter_ip=None,
            )

        # Redis.incr must NOT be called since no IP was provided
        redis.incr.assert_not_called()

    @pytest.mark.asyncio
    async def test_rate_limit_redis_incr_called_with_ip(self) -> None:
        db, _ = _make_mock_db()
        redis = _make_mock_redis(incr_return=6)

        with pytest.raises(RateLimitError):
            await create_user(
                db,
                redis,
                email="teacher@school.edu",
                password="Pass1234",
                first_name="Alex",
                last_name="Smith",
                school_name="Test School",
                submitter_ip="10.0.0.1",
            )

        expected_key = _signup_rate_limit_key("10.0.0.1")
        redis.incr.assert_awaited_once_with(expected_key)


# ---------------------------------------------------------------------------
# verify_email
# ---------------------------------------------------------------------------


class TestVerifyEmailService:
    @pytest.mark.asyncio
    async def test_raises_validation_error_when_token_invalid(self) -> None:
        db, _ = _make_mock_db()
        redis = _make_mock_redis()
        redis.getdel = AsyncMock(return_value=None)

        with pytest.raises(ValidationError):
            await verify_email(db, redis, "invalid_token")

    @pytest.mark.asyncio
    async def test_raises_validation_error_when_user_not_found(self) -> None:
        user_id = uuid.uuid4()
        db, _ = _make_mock_db()
        redis = _make_mock_redis()
        redis.getdel = AsyncMock(return_value=str(user_id))

        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=None)
        db.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(ValidationError):
            await verify_email(db, redis, "good_token")

    @pytest.mark.asyncio
    async def test_returns_user_idempotently_when_already_verified(self) -> None:
        user_id = uuid.uuid4()
        db, _ = _make_mock_db()
        redis = _make_mock_redis()
        redis.getdel = AsyncMock(return_value=str(user_id))

        fake_user = MagicMock()
        fake_user.id = user_id
        fake_user.email_verified = True  # already verified
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=fake_user)
        db.execute = AsyncMock(return_value=mock_result)

        result = await verify_email(db, redis, "some_token")

        assert result is fake_user
        db.commit.assert_not_awaited()  # no re-commit needed


# ---------------------------------------------------------------------------
# resend_verification
# ---------------------------------------------------------------------------


class TestResendVerificationService:
    @pytest.mark.asyncio
    async def test_raises_rate_limit_error_when_limit_exceeded(self) -> None:
        db, _ = _make_mock_db()
        redis = _make_mock_redis(incr_return=4)  # exceeds limit of 3

        with pytest.raises(RateLimitError):
            await resend_verification(db, redis, "teacher@school.edu", submitter_ip=None)

    @pytest.mark.asyncio
    async def test_returns_none_when_email_not_registered(self) -> None:
        db, _ = _make_mock_db()
        redis = _make_mock_redis(incr_return=1)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=None)
        db.execute = AsyncMock(return_value=mock_result)

        result = await resend_verification(db, redis, "notfound@school.edu", submitter_ip=None)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_already_verified(self) -> None:
        db, _ = _make_mock_db()
        redis = _make_mock_redis(incr_return=1)

        fake_user = MagicMock()
        fake_user.email_verified = True
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=fake_user)
        db.execute = AsyncMock(return_value=mock_result)

        result = await resend_verification(db, redis, "verified@school.edu", submitter_ip=None)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_user_when_unverified_account_found(self) -> None:
        db, _ = _make_mock_db()
        redis = _make_mock_redis(incr_return=1)

        fake_user = MagicMock()
        fake_user.id = uuid.uuid4()
        fake_user.email_verified = False
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=fake_user)
        db.execute = AsyncMock(return_value=mock_result)

        result = await resend_verification(db, redis, "unverified@school.edu", submitter_ip=None)
        assert result is fake_user

    @pytest.mark.asyncio
    async def test_rate_limit_key_is_hashed(self) -> None:
        """Resend rate-limit key must not contain the raw email address."""
        email = "teacher@school.edu"
        db, _ = _make_mock_db()
        redis = _make_mock_redis(incr_return=4)

        with pytest.raises(RateLimitError):
            await resend_verification(db, redis, email, submitter_ip=None)

        key = _resend_rate_limit_key(email)
        assert email not in key  # email must be hashed, not stored in key
        redis.incr.assert_awaited_once_with(key)
