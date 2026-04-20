"""Unit tests for app/services/rubric_template.py.

Tests cover:
- list_rubric_templates: system + personal results, empty result
- save_rubric_as_template: success, not-found, cross-teacher

No real PostgreSQL.  All DB calls are mocked.  No student PII in fixtures.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.exceptions import ForbiddenError, NotFoundError
from app.services.rubric_template import list_rubric_templates, save_rubric_as_template

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_rubric_orm(
    teacher_id: uuid.UUID | None = None,
    rubric_id: uuid.UUID | None = None,
    name: str = "Test Rubric",
    is_template: bool = True,
) -> MagicMock:
    rubric = MagicMock()
    rubric.id = rubric_id or uuid.uuid4()
    rubric.teacher_id = teacher_id
    rubric.name = name
    rubric.description = "A test rubric"
    rubric.is_template = is_template
    rubric.deleted_at = None
    return rubric


def _make_criterion_orm(
    rubric_id: uuid.UUID | None = None,
    display_order: int = 0,
) -> MagicMock:
    c = MagicMock()
    c.id = uuid.uuid4()
    c.rubric_id = rubric_id or uuid.uuid4()
    c.name = "Thesis"
    c.description = "A criterion"
    c.weight = Decimal("50")
    c.min_score = 1
    c.max_score = 5
    c.display_order = display_order
    c.anchor_descriptions = None
    return c


def _make_db() -> AsyncMock:
    return AsyncMock()


# ---------------------------------------------------------------------------
# list_rubric_templates
# ---------------------------------------------------------------------------


class TestListRubricTemplates:
    @pytest.mark.asyncio
    async def test_returns_empty_when_no_templates(self) -> None:
        db = _make_db()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(return_value=mock_result)

        result = await list_rubric_templates(db, uuid.uuid4())

        assert result == []

    @pytest.mark.asyncio
    async def test_returns_system_and_personal_templates(self) -> None:
        teacher_id = uuid.uuid4()
        system_rubric = _make_rubric_orm(teacher_id=None, name="System Template")
        personal_rubric = _make_rubric_orm(teacher_id=teacher_id, name="Personal Template")
        criterion_sys = _make_criterion_orm(rubric_id=system_rubric.id)
        criterion_pers = _make_criterion_orm(rubric_id=personal_rubric.id)

        db = _make_db()
        # First execute: returns rubrics; second: returns criteria.
        rubric_result = MagicMock()
        rubric_result.scalars.return_value.all.return_value = [
            system_rubric,
            personal_rubric,
        ]
        criteria_result = MagicMock()
        criteria_result.scalars.return_value.all.return_value = [
            criterion_sys,
            criterion_pers,
        ]
        db.execute = AsyncMock(side_effect=[rubric_result, criteria_result])

        result = await list_rubric_templates(db, teacher_id)

        assert len(result) == 2
        # System template: teacher_id is None → is_system=True
        r0, c0, is_system0 = result[0]
        assert r0.name == "System Template"
        assert is_system0 is True
        # Personal template: teacher_id is teacher_id → is_system=False
        r1, c1, is_system1 = result[1]
        assert r1.name == "Personal Template"
        assert is_system1 is False


# ---------------------------------------------------------------------------
# save_rubric_as_template
# ---------------------------------------------------------------------------


class TestSaveRubricAsTemplate:
    @pytest.mark.asyncio
    async def test_raises_not_found_when_rubric_missing(self) -> None:
        db = _make_db()
        ownership_result = MagicMock()
        ownership_result.one_or_none.return_value = None
        db.execute = AsyncMock(return_value=ownership_result)

        with pytest.raises(NotFoundError):
            await save_rubric_as_template(db, uuid.uuid4(), uuid.uuid4())

    @pytest.mark.asyncio
    async def test_raises_forbidden_for_cross_teacher(self) -> None:
        teacher_id = uuid.uuid4()
        other_teacher_id = uuid.uuid4()
        rubric_id = uuid.uuid4()

        db = _make_db()
        ownership_row = MagicMock()
        ownership_row.teacher_id = other_teacher_id  # different teacher
        ownership_result = MagicMock()
        ownership_result.one_or_none.return_value = ownership_row
        db.execute = AsyncMock(return_value=ownership_result)

        with pytest.raises(ForbiddenError):
            await save_rubric_as_template(db, teacher_id, rubric_id)

    @pytest.mark.asyncio
    async def test_creates_template_copy(self) -> None:
        teacher_id = uuid.uuid4()
        rubric_id = uuid.uuid4()
        source_rubric = _make_rubric_orm(teacher_id=teacher_id, rubric_id=rubric_id)
        criterion = _make_criterion_orm(rubric_id=rubric_id)

        db = _make_db()

        # Execute calls: (1) ownership check, (2) full rubric load, (3) criteria load
        ownership_row = MagicMock()
        ownership_row.teacher_id = teacher_id
        ownership_result = MagicMock()
        ownership_result.one_or_none.return_value = ownership_row

        full_rubric_result = MagicMock()
        full_rubric_result.scalar_one_or_none.return_value = source_rubric

        criteria_result = MagicMock()
        criteria_result.scalars.return_value.all.return_value = [criterion]

        db.execute = AsyncMock(
            side_effect=[ownership_result, full_rubric_result, criteria_result]
        )
        db.flush = AsyncMock()

        added_items: list[object] = []
        db.add = MagicMock(side_effect=added_items.append)
        db.commit = AsyncMock()

        # Capture the template rubric passed to db.add so we can assert on it.
        template_rubric = _make_rubric_orm(teacher_id=teacher_id)
        template_rubric.is_template = True

        async def fake_refresh(obj: object) -> None:
            pass

        db.refresh = AsyncMock(side_effect=fake_refresh)

        # Patch only the db.flush to set template_rubric.id after flush
        # (simulating what the real DB would do).
        async def fake_flush() -> None:
            # The newly added Rubric instance is the first item in added_items.
            if added_items:
                added_items[0].id = template_rubric.id  # type: ignore[attr-defined]

        db.flush = AsyncMock(side_effect=fake_flush)

        result_rubric, result_criteria = await save_rubric_as_template(
            db, teacher_id, rubric_id
        )

        # Verify that db.add was called (at least for the new Rubric).
        assert db.add.called
        assert db.commit.called

    @pytest.mark.asyncio
    async def test_uses_name_override_when_provided(self) -> None:
        teacher_id = uuid.uuid4()
        rubric_id = uuid.uuid4()
        source_rubric = _make_rubric_orm(teacher_id=teacher_id, rubric_id=rubric_id, name="Original")

        db = _make_db()

        ownership_row = MagicMock()
        ownership_row.teacher_id = teacher_id
        ownership_result = MagicMock()
        ownership_result.one_or_none.return_value = ownership_row

        full_rubric_result = MagicMock()
        full_rubric_result.scalar_one_or_none.return_value = source_rubric

        criteria_result = MagicMock()
        criteria_result.scalars.return_value.all.return_value = []

        db.execute = AsyncMock(
            side_effect=[ownership_result, full_rubric_result, criteria_result]
        )
        db.flush = AsyncMock()

        added_items: list[object] = []
        db.add = MagicMock(side_effect=added_items.append)
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        await save_rubric_as_template(db, teacher_id, rubric_id, name="My Override")

        # The first item added should be the new Rubric with the overridden name.
        assert len(added_items) >= 1
        new_rubric = added_items[0]
        assert new_rubric.name == "My Override", (  # type: ignore[attr-defined]
            f"Expected name 'My Override', got {new_rubric.name!r}"  # type: ignore[attr-defined]
        )
        assert new_rubric.is_template is True  # type: ignore[attr-defined]
