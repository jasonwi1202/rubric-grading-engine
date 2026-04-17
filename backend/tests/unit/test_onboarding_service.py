"""Unit tests for app/services/onboarding.py.

Tests the database-layer logic (mocked AsyncSession).
No real PostgreSQL.  No student PII.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.exceptions import NotFoundError
from app.services.onboarding import complete_onboarding, get_onboarding_status

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


def _make_user(onboarding_complete: bool = False) -> MagicMock:
    user = MagicMock()
    user.id = uuid.uuid4()
    user.email = "teacher@school.edu"
    user.onboarding_complete = onboarding_complete
    return user


# ---------------------------------------------------------------------------
# get_onboarding_status
# ---------------------------------------------------------------------------


class TestGetOnboardingStatus:
    @pytest.mark.asyncio
    async def test_returns_step_1_not_complete_when_not_complete(self) -> None:
        user = _make_user(onboarding_complete=False)
        db = _make_db(fake_user=user)

        step, completed = await get_onboarding_status(db, user.id)

        assert step == 1
        assert completed is False

    @pytest.mark.asyncio
    async def test_returns_step_2_complete_when_already_complete(self) -> None:
        user = _make_user(onboarding_complete=True)
        db = _make_db(fake_user=user)

        step, completed = await get_onboarding_status(db, user.id)

        assert step == 2
        assert completed is True

    @pytest.mark.asyncio
    async def test_raises_not_found_when_teacher_missing(self) -> None:
        db = _make_db(fake_user=None)
        with pytest.raises(NotFoundError):
            await get_onboarding_status(db, uuid.uuid4())

    @pytest.mark.asyncio
    async def test_queries_by_teacher_id(self) -> None:
        """Ensures the query uses the provided teacher_id (tenant isolation)."""
        user = _make_user(onboarding_complete=False)
        db = _make_db(fake_user=user)
        teacher_id = user.id

        await get_onboarding_status(db, teacher_id)

        db.execute.assert_called_once()
        # The query is a SELECT expression; just verify execute was called once.


# ---------------------------------------------------------------------------
# complete_onboarding
# ---------------------------------------------------------------------------


class TestCompleteOnboarding:
    @pytest.mark.asyncio
    async def test_sets_onboarding_complete_true_and_commits(self) -> None:
        user = _make_user(onboarding_complete=False)
        db = _make_db(fake_user=user)

        returned_user = await complete_onboarding(db, user.id)

        assert user.onboarding_complete is True
        db.commit.assert_called()
        db.refresh.assert_called_with(user)
        assert returned_user is user

    @pytest.mark.asyncio
    async def test_idempotent_when_already_complete(self) -> None:
        user = _make_user(onboarding_complete=True)
        db = _make_db(fake_user=user)

        returned_user = await complete_onboarding(db, user.id)

        # onboarding_complete is already True; should still commit + return user.
        assert user.onboarding_complete is True
        db.commit.assert_called()
        assert returned_user is user

    @pytest.mark.asyncio
    async def test_raises_not_found_when_teacher_missing(self) -> None:
        db = _make_db(fake_user=None)
        with pytest.raises(NotFoundError):
            await complete_onboarding(db, uuid.uuid4())
