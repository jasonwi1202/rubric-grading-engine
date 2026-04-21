"""Unit tests for app/services/comment_bank.py.

Tests cover:
- list_comments: returns all comments for a teacher, newest-first
- create_comment: success path
- delete_comment: success, not-found, cross-teacher (ForbiddenError)
- suggest_comments: returns matches above threshold, excludes non-matches,
  normalises score, orders by descending score

No real PostgreSQL.  All DB calls are mocked.  No student PII in fixtures.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.exceptions import ForbiddenError, NotFoundError
from app.models.comment_bank import CommentBankEntry
from app.services.comment_bank import (
    create_comment,
    delete_comment,
    list_comments,
    suggest_comments,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_entry(
    teacher_id: uuid.UUID | None = None,
    text: str = "Good use of evidence.",
    comment_id: uuid.UUID | None = None,
) -> MagicMock:
    entry = MagicMock(spec=CommentBankEntry)
    entry.id = comment_id or uuid.uuid4()
    entry.teacher_id = teacher_id or uuid.uuid4()
    entry.text = text
    return entry


def _make_db(entries: list[MagicMock] | None = None) -> AsyncMock:
    """Return a minimal AsyncSession mock that yields *entries* from execute."""
    db = AsyncMock()
    scalars = MagicMock()
    scalars.all.return_value = entries or []
    result = MagicMock()
    result.scalars.return_value = scalars
    result.scalar_one_or_none.return_value = (entries or [None])[0]
    db.execute = AsyncMock(return_value=result)
    db.add = MagicMock()
    db.delete = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


# ---------------------------------------------------------------------------
# list_comments
# ---------------------------------------------------------------------------


class TestListComments:
    @pytest.mark.asyncio
    async def test_returns_all_entries(self) -> None:
        teacher_id = uuid.uuid4()
        entries = [_make_entry(teacher_id=teacher_id), _make_entry(teacher_id=teacher_id)]
        db = _make_db(entries)

        result = await list_comments(db, teacher_id)

        assert result == entries
        db.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_entries(self) -> None:
        db = _make_db([])
        result = await list_comments(db, uuid.uuid4())
        assert result == []


# ---------------------------------------------------------------------------
# create_comment
# ---------------------------------------------------------------------------


class TestCreateComment:
    @pytest.mark.asyncio
    async def test_success(self) -> None:
        teacher_id = uuid.uuid4()
        db = AsyncMock()
        db.add = MagicMock()
        db.commit = AsyncMock()

        created_entry = _make_entry(teacher_id=teacher_id, text="Strong thesis.")

        async def _refresh(obj: object) -> None:
            # Simulate db.refresh populating the entry
            pass

        db.refresh = AsyncMock(side_effect=_refresh)

        # Patch CommentBankEntry constructor to return a known mock
        import app.services.comment_bank as svc

        original_cls = svc.CommentBankEntry
        mock_entry_cls = MagicMock(return_value=created_entry)
        svc.CommentBankEntry = mock_entry_cls  # type: ignore[assignment]
        try:
            result = await create_comment(db, teacher_id, "Strong thesis.")
        finally:
            svc.CommentBankEntry = original_cls  # type: ignore[assignment]

        db.add.assert_called_once_with(created_entry)
        db.commit.assert_awaited_once()
        db.refresh.assert_awaited_once_with(created_entry)
        assert result is created_entry

    @pytest.mark.asyncio
    async def test_db_add_is_not_awaited(self) -> None:
        """db.add() must be called synchronously — never awaited."""
        teacher_id = uuid.uuid4()
        db = AsyncMock()
        db.add = MagicMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        import app.services.comment_bank as svc

        original_cls = svc.CommentBankEntry
        entry = _make_entry(teacher_id=teacher_id)
        svc.CommentBankEntry = MagicMock(return_value=entry)  # type: ignore[assignment]
        try:
            await create_comment(db, teacher_id, "text")
        finally:
            svc.CommentBankEntry = original_cls  # type: ignore[assignment]

        # add must be a MagicMock (not awaited), commit is awaited
        assert isinstance(db.add, MagicMock)
        db.commit.assert_awaited_once()


# ---------------------------------------------------------------------------
# delete_comment
# ---------------------------------------------------------------------------


class TestDeleteComment:
    @pytest.mark.asyncio
    async def test_success(self) -> None:
        teacher_id = uuid.uuid4()
        comment_id = uuid.uuid4()
        entry = _make_entry(teacher_id=teacher_id, comment_id=comment_id)
        db = _make_db([entry])
        db.delete = MagicMock()

        await delete_comment(db, teacher_id, comment_id)

        db.delete.assert_called_once_with(entry)
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_not_found(self) -> None:
        db = _make_db([None])
        db.execute.return_value.scalar_one_or_none.return_value = None

        with pytest.raises(NotFoundError):
            await delete_comment(db, uuid.uuid4(), uuid.uuid4())

    @pytest.mark.asyncio
    async def test_cross_teacher_raises_forbidden(self) -> None:
        owner_id = uuid.uuid4()
        other_teacher_id = uuid.uuid4()
        comment_id = uuid.uuid4()
        entry = _make_entry(teacher_id=owner_id, comment_id=comment_id)
        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = entry
        db.execute = AsyncMock(return_value=result)

        with pytest.raises(ForbiddenError):
            await delete_comment(db, other_teacher_id, comment_id)

    @pytest.mark.asyncio
    async def test_db_delete_is_not_awaited(self) -> None:
        """db.delete() must be called synchronously — never awaited."""
        teacher_id = uuid.uuid4()
        comment_id = uuid.uuid4()
        entry = _make_entry(teacher_id=teacher_id, comment_id=comment_id)
        db = AsyncMock()
        db.delete = MagicMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = entry
        db.execute = AsyncMock(return_value=result)
        db.commit = AsyncMock()

        await delete_comment(db, teacher_id, comment_id)

        assert isinstance(db.delete, MagicMock)


# ---------------------------------------------------------------------------
# suggest_comments
# ---------------------------------------------------------------------------


class TestSuggestComments:
    @pytest.mark.asyncio
    async def test_returns_matching_entries(self) -> None:
        teacher_id = uuid.uuid4()
        matching = _make_entry(teacher_id=teacher_id, text="Good use of textual evidence.")
        non_matching = _make_entry(teacher_id=teacher_id, text="zxqwerty nonsense gibberish")
        db = _make_db([matching, non_matching])

        results = await suggest_comments(db, teacher_id, "evidence")

        ids = [e.id for e, _ in results]
        assert matching.id in ids
        assert non_matching.id not in ids

    @pytest.mark.asyncio
    async def test_scores_are_normalised_between_0_and_1(self) -> None:
        teacher_id = uuid.uuid4()
        entry = _make_entry(teacher_id=teacher_id, text="Strong thesis statement.")
        db = _make_db([entry])

        results = await suggest_comments(db, teacher_id, "thesis")

        for _, score in results:
            assert 0.0 <= score <= 1.0, f"Score {score} out of range"

    @pytest.mark.asyncio
    async def test_results_ordered_by_descending_score(self) -> None:
        teacher_id = uuid.uuid4()
        # "evidence" matches the first entry more closely than the second
        high = _make_entry(teacher_id=teacher_id, text="Evidence is compelling.")
        low = _make_entry(teacher_id=teacher_id, text="The essay uses evidence well overall.")
        db = _make_db([low, high])

        results = await suggest_comments(db, teacher_id, "evidence")

        scores = [s for _, s in results]
        assert scores == sorted(scores, reverse=True), "Results must be sorted highest score first"

    @pytest.mark.asyncio
    async def test_empty_bank_returns_empty(self) -> None:
        db = _make_db([])
        results = await suggest_comments(db, uuid.uuid4(), "anything")
        assert results == []

    @pytest.mark.asyncio
    async def test_no_matches_returns_empty(self) -> None:
        teacher_id = uuid.uuid4()
        entry = _make_entry(teacher_id=teacher_id, text="zxqwerty nonsense gibberish xyz")
        db = _make_db([entry])

        results = await suggest_comments(db, teacher_id, "evidence")

        assert results == []
