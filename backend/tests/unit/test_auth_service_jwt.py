"""Unit tests for the JWT/session helper functions added in M2.9.

Tests cover:
- create_access_token / decode_access_token
- create_refresh_token
- store_refresh_token / consume_refresh_token / delete_refresh_token
- login_user (happy path + every failure branch)
- refresh_access_token (happy path + failure branches)
- logout_user

No real PostgreSQL, Redis, or OpenAI calls.  All I/O is mocked.
No student PII in fixtures.
"""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.exceptions import RefreshTokenInvalidError, UnauthorizedError, ValidationError
from app.services.auth import (
    consume_refresh_token,
    create_access_token,
    create_refresh_token,
    decode_access_token,
    delete_refresh_token,
    logout_user,
    refresh_access_token,
    store_refresh_token,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_db(fake_user: MagicMock | None = None) -> AsyncMock:
    db = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    scalar_mock = MagicMock()
    scalar_mock.scalar_one_or_none = MagicMock(return_value=fake_user)
    db.execute = AsyncMock(return_value=scalar_mock)
    return db


def _make_redis(getdel_return: str | None = None) -> AsyncMock:
    redis = AsyncMock()
    redis.set = AsyncMock()
    redis.getdel = AsyncMock(return_value=getdel_return)
    redis.delete = AsyncMock()
    return redis


def _make_fake_user(
    verified: bool = True,
    password_hash: str | None = None,
) -> MagicMock:
    user = MagicMock()
    user.id = uuid.uuid4()
    user.email = "teacher@school.edu"
    user.first_name = "Alex"
    user.last_name = "Smith"
    user.email_verified = verified
    user.hashed_password = password_hash or "$2b$12$placeholder_hash"
    user.last_login_at = None
    return user


# ---------------------------------------------------------------------------
# create_access_token / decode_access_token
# ---------------------------------------------------------------------------


class TestCreateDecodeAccessToken:
    def test_roundtrip(self) -> None:
        user_id = uuid.uuid4()
        email = "teacher@school.edu"
        token = create_access_token(user_id, email)
        payload = decode_access_token(token)
        assert payload["sub"] == str(user_id)
        assert payload["email"] == email
        assert payload["type"] == "access"

    def test_default_ttl_is_fifteen_minutes(self) -> None:
        """create_access_token uses the 15-min default when short_lived_token_ttl_seconds is None."""
        import jwt as pyjwt

        from app.config import settings

        assert settings.short_lived_token_ttl_seconds is None
        token = create_access_token(uuid.uuid4(), "teacher@school.edu")
        payload = pyjwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
            options={"verify_exp": False},
        )
        ttl = payload["exp"] - payload["iat"]
        assert ttl == 15 * 60

    def test_short_lived_ttl_overrides_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """create_access_token uses short_lived_token_ttl_seconds when set."""
        import jwt as pyjwt

        from app.config import settings

        monkeypatch.setattr(settings, "short_lived_token_ttl_seconds", 5)
        token = create_access_token(uuid.uuid4(), "teacher@school.edu")
        payload = pyjwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
            options={"verify_exp": False},
        )
        ttl = payload["exp"] - payload["iat"]
        assert ttl == 5
        monkeypatch.setattr(settings, "short_lived_token_ttl_seconds", None)  # restore

    def test_expired_token_raises_validation_error(self) -> None:
        import jwt as pyjwt

        from app.config import settings

        now = datetime.now(UTC)
        payload = {
            "sub": str(uuid.uuid4()),
            "email": "expired@school.edu",
            "type": "access",
            "iat": now - timedelta(minutes=30),
            "exp": now - timedelta(minutes=15),
        }
        expired_token = pyjwt.encode(
            payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm
        )
        with pytest.raises(ValidationError, match="expired"):
            decode_access_token(expired_token)

    def test_invalid_signature_raises_validation_error(self) -> None:
        import jwt as pyjwt

        now = datetime.now(UTC)
        payload = {
            "sub": str(uuid.uuid4()),
            "email": "x@school.edu",
            "type": "access",
            "iat": now,
            "exp": now + timedelta(minutes=15),
        }
        # Sign with a different key to force signature mismatch
        bad_token = pyjwt.encode(
            payload, "wrong_secret_key_that_is_long_enough_for_hmac", algorithm="HS256"
        )
        with pytest.raises(ValidationError, match="invalid"):
            decode_access_token(bad_token)

    def test_different_users_produce_different_tokens(self) -> None:
        t1 = create_access_token(uuid.uuid4(), "a@school.edu")
        t2 = create_access_token(uuid.uuid4(), "b@school.edu")
        assert t1 != t2


# ---------------------------------------------------------------------------
# create_refresh_token
# ---------------------------------------------------------------------------


class TestCreateRefreshToken:
    def test_returns_non_empty_string(self) -> None:
        token = create_refresh_token()
        assert isinstance(token, str)
        assert len(token) > 32

    def test_different_calls_produce_different_tokens(self) -> None:
        t1 = create_refresh_token()
        t2 = create_refresh_token()
        assert t1 != t2


# ---------------------------------------------------------------------------
# store_refresh_token / consume_refresh_token / delete_refresh_token
# ---------------------------------------------------------------------------


class TestRefreshTokenRedisHelpers:
    @pytest.mark.asyncio
    async def test_store_calls_redis_set_with_correct_key(self) -> None:
        redis = _make_redis()
        user_id = uuid.uuid4()
        token = "test_token_abc"
        await store_refresh_token(redis, token, user_id, 604800)
        redis.set.assert_called_once()
        key_arg = redis.set.call_args[0][0]
        # The key format is auth:refresh:<token>
        assert "auth:refresh:" in key_arg
        assert token in key_arg
        value_arg = redis.set.call_args[0][1]
        assert str(user_id) == value_arg

    @pytest.mark.asyncio
    async def test_consume_returns_user_id_when_token_valid(self) -> None:
        user_id = uuid.uuid4()
        redis = _make_redis(getdel_return=str(user_id))
        result = await consume_refresh_token(redis, "any_token")
        assert result == user_id

    @pytest.mark.asyncio
    async def test_consume_returns_none_when_token_missing(self) -> None:
        redis = _make_redis(getdel_return=None)
        result = await consume_refresh_token(redis, "missing_token")
        assert result is None

    @pytest.mark.asyncio
    async def test_consume_returns_none_when_stored_value_invalid_uuid(self) -> None:
        redis = _make_redis(getdel_return="not-a-uuid")
        result = await consume_refresh_token(redis, "bad_value_token")
        assert result is None

    @pytest.mark.asyncio
    async def test_delete_calls_redis_delete(self) -> None:
        redis = _make_redis()
        token = "token_to_delete"
        await delete_refresh_token(redis, token)
        redis.delete.assert_called_once()
        key_arg = redis.delete.call_args[0][0]
        assert token in key_arg


# ---------------------------------------------------------------------------
# login_user
# ---------------------------------------------------------------------------


class TestLoginUser:
    @pytest.mark.asyncio
    async def test_login_failure_user_not_found(self) -> None:
        db = _make_db(fake_user=None)
        redis = _make_redis()
        with pytest.raises(UnauthorizedError, match="Invalid email or password"):
            from app.services.auth import login_user

            await login_user(db, redis, "nobody@school.edu", "password123")
        db.commit.assert_called()

    @pytest.mark.asyncio
    async def test_login_failure_email_not_verified(self) -> None:
        user = _make_fake_user(verified=False)
        db = _make_db(fake_user=user)
        redis = _make_redis()
        with pytest.raises(UnauthorizedError, match="verify your email"):
            from app.services.auth import login_user

            await login_user(db, redis, user.email, "password123")
        db.commit.assert_called()

    @pytest.mark.asyncio
    async def test_login_failure_wrong_password(self) -> None:
        import bcrypt

        hashed = bcrypt.hashpw(b"correct_pass", bcrypt.gensalt()).decode()
        user = _make_fake_user(verified=True, password_hash=hashed)
        db = _make_db(fake_user=user)
        redis = _make_redis()
        with pytest.raises(UnauthorizedError, match="Invalid email or password"):
            from app.services.auth import login_user

            await login_user(db, redis, user.email, "wrong_pass")
        db.commit.assert_called()

    @pytest.mark.asyncio
    async def test_login_success_returns_user_and_tokens(self) -> None:
        import bcrypt

        hashed = bcrypt.hashpw(b"correct_pass", bcrypt.gensalt()).decode()
        user = _make_fake_user(verified=True, password_hash=hashed)
        db = _make_db(fake_user=user)
        redis = _make_redis()

        from app.services.auth import login_user

        result_user, access_token, refresh_token = await login_user(
            db, redis, user.email, "correct_pass"
        )
        assert result_user is user
        assert isinstance(access_token, str) and len(access_token) > 0
        assert isinstance(refresh_token, str) and len(refresh_token) > 0
        db.commit.assert_called()
        redis.set.assert_called()


# ---------------------------------------------------------------------------
# refresh_access_token
# ---------------------------------------------------------------------------


class TestRefreshAccessToken:
    @pytest.mark.asyncio
    async def test_refresh_fails_when_token_invalid(self) -> None:
        db = _make_db(fake_user=None)
        redis = _make_redis(getdel_return=None)
        with pytest.raises(RefreshTokenInvalidError, match="invalid or has expired"):
            await refresh_access_token(db, redis, refresh_token="invalid_token")

    @pytest.mark.asyncio
    async def test_refresh_fails_when_user_not_found(self) -> None:
        user_id = uuid.uuid4()
        db = _make_db(fake_user=None)
        redis = _make_redis(getdel_return=str(user_id))
        with pytest.raises(RefreshTokenInvalidError, match="invalid or has expired"):
            await refresh_access_token(db, redis, refresh_token="valid_token_but_no_user")

    @pytest.mark.asyncio
    async def test_refresh_fails_when_user_unverified(self) -> None:
        user = _make_fake_user(verified=False)
        db = _make_db(fake_user=user)
        redis = _make_redis(getdel_return=str(user.id))
        with pytest.raises(RefreshTokenInvalidError, match="invalid or has expired"):
            await refresh_access_token(db, redis, refresh_token="token_for_unverified")

    @pytest.mark.asyncio
    async def test_refresh_success_returns_new_tokens(self) -> None:
        user = _make_fake_user(verified=True)
        db = _make_db(fake_user=user)
        redis = _make_redis(getdel_return=str(user.id))

        result_user, new_access, new_refresh = await refresh_access_token(
            db, redis, refresh_token="good_token"
        )
        assert result_user is user
        assert isinstance(new_access, str) and len(new_access) > 0
        assert isinstance(new_refresh, str) and len(new_refresh) > 0
        db.commit.assert_called()
        redis.set.assert_called()


# ---------------------------------------------------------------------------
# logout_user
# ---------------------------------------------------------------------------


class TestLogoutUser:
    @pytest.mark.asyncio
    async def test_logout_deletes_refresh_token_and_writes_audit(self) -> None:
        teacher_id = uuid.uuid4()
        db = _make_db()
        redis = _make_redis()

        await logout_user(db, redis, "some_refresh_token", teacher_id)

        redis.delete.assert_called_once()
        db.add.assert_called_once()
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_logout_audit_action_is_logout(self) -> None:
        teacher_id = uuid.uuid4()
        db = _make_db()
        redis = _make_redis()

        await logout_user(db, redis, "token", teacher_id)

        audit_arg = db.add.call_args[0][0]
        assert audit_arg.action == "logout"
        assert audit_arg.teacher_id == teacher_id
