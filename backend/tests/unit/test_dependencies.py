"""Unit tests for app/dependencies.py.

Tests:
- get_current_teacher: valid token, missing credentials, invalid token, user not found,
  unverified email
- get_current_teacher_optional: various header shapes

No real PostgreSQL or Redis.  All DB calls are mocked.
No student PII in fixtures.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.security import HTTPAuthorizationCredentials

from app.config import settings
from app.dependencies import get_current_teacher, get_current_teacher_optional
from app.exceptions import UnauthorizedError
from app.services.auth import create_access_token

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_db(fake_user: MagicMock | None = None) -> AsyncMock:
    db = AsyncMock()
    scalar_mock = MagicMock()
    scalar_mock.scalar_one_or_none = MagicMock(return_value=fake_user)
    db.execute = AsyncMock(return_value=scalar_mock)
    return db


def _make_user(verified: bool = True) -> MagicMock:
    user = MagicMock()
    user.id = uuid.uuid4()
    user.email = "teacher@school.edu"
    user.email_verified = verified
    return user


def _make_credentials(token: str) -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


# ---------------------------------------------------------------------------
# get_current_teacher — direct async tests
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _force_dependency_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep dependency tests deterministic regardless of local .env settings."""
    monkeypatch.setattr(settings, "allow_unverified_login_in_test", False)


class TestGetCurrentTeacher:
    @pytest.mark.asyncio
    async def test_valid_token_returns_user(self) -> None:
        user = _make_user(verified=True)
        token = create_access_token(user.id, user.email)
        credentials = _make_credentials(token)
        db = _make_db(fake_user=user)

        result = await get_current_teacher(credentials=credentials, db=db)
        assert result is user

    @pytest.mark.asyncio
    async def test_no_credentials_raises_unauthorized(self) -> None:
        db = _make_db()
        with pytest.raises(UnauthorizedError):
            await get_current_teacher(credentials=None, db=db)

    @pytest.mark.asyncio
    async def test_invalid_token_raises_unauthorized(self) -> None:
        credentials = _make_credentials("not_a_valid_jwt_token")
        db = _make_db()
        with pytest.raises(UnauthorizedError):
            await get_current_teacher(credentials=credentials, db=db)

    @pytest.mark.asyncio
    async def test_wrong_token_type_raises_unauthorized(self) -> None:
        """A JWT with type != 'access' (e.g. a future refresh-JWT) must be rejected."""
        import jwt as pyjwt

        from app.config import settings

        bad_token = pyjwt.encode(
            {"sub": str(uuid.uuid4()), "type": "refresh"},
            settings.jwt_secret_key,
            algorithm="HS256",
        )
        credentials = _make_credentials(bad_token)
        db = _make_db()
        with pytest.raises(UnauthorizedError, match="Invalid token type"):
            await get_current_teacher(credentials=credentials, db=db)

    @pytest.mark.asyncio
    async def test_user_not_found_raises_unauthorized(self) -> None:
        user_id = uuid.uuid4()
        token = create_access_token(user_id, "ghost@school.edu")
        credentials = _make_credentials(token)
        db = _make_db(fake_user=None)

        with pytest.raises(UnauthorizedError, match="Account not found"):
            await get_current_teacher(credentials=credentials, db=db)

    @pytest.mark.asyncio
    async def test_unverified_email_raises_unauthorized(self) -> None:
        user = _make_user(verified=False)
        token = create_access_token(user.id, user.email)
        credentials = _make_credentials(token)
        db = _make_db(fake_user=user)

        with pytest.raises(UnauthorizedError, match="not verified"):
            await get_current_teacher(credentials=credentials, db=db)


# ---------------------------------------------------------------------------
# get_current_teacher_optional — direct async tests
# ---------------------------------------------------------------------------


class TestGetCurrentTeacherOptional:
    @pytest.mark.asyncio
    async def test_returns_none_when_no_auth_header(self) -> None:
        request = MagicMock()
        request.headers = {}
        db = _make_db()

        result = await get_current_teacher_optional(request, db)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_for_non_bearer_header(self) -> None:
        request = MagicMock()
        request.headers = {"Authorization": "Basic dXNlcjpwYXNz"}
        db = _make_db()

        result = await get_current_teacher_optional(request, db)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_uuid_for_valid_token(self) -> None:
        user_id = uuid.uuid4()
        token = create_access_token(user_id, "teacher@school.edu")

        request = MagicMock()
        request.headers = {"Authorization": f"Bearer {token}"}
        db = _make_db()

        result = await get_current_teacher_optional(request, db)
        assert result == user_id

    @pytest.mark.asyncio
    async def test_returns_none_for_invalid_token(self) -> None:
        request = MagicMock()
        request.headers = {"Authorization": "Bearer not_a_real_token"}
        db = _make_db()

        result = await get_current_teacher_optional(request, db)
        assert result is None

    @pytest.mark.asyncio
    async def test_accepts_lowercase_bearer_scheme(self) -> None:
        """HTTP auth schemes are case-insensitive (RFC 7235 §2.1)."""
        user_id = uuid.uuid4()
        token = create_access_token(user_id, "teacher@school.edu")

        request = MagicMock()
        request.headers = {"Authorization": f"bearer {token}"}
        db = _make_db()

        result = await get_current_teacher_optional(request, db)
        assert result == user_id
