"""Unit tests for app/services/rubric.py.

Tests cover:
- _validate_weight_sum: valid and invalid weight sums
- create_rubric: success path + weight-sum validation failure
- get_rubric: success, not-found, cross-teacher
- delete_rubric: success, in-use block, cross-teacher
- duplicate_rubric: success path
- build_rubric_snapshot: output structure

No real PostgreSQL.  All DB calls are mocked.  No student PII in fixtures.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.exceptions import ForbiddenError, NotFoundError, RubricInUseError, RubricWeightInvalidError
from app.schemas.rubric import RubricCriterionRequest
from app.services.rubric import (
    _validate_weight_sum,  # noqa: PLC2701 — testing internal helper
    build_rubric_snapshot,
    create_rubric,
    delete_rubric,
    duplicate_rubric,
    get_rubric,
)

# ---------------------------------------------------------------------------
# Fixtures / Helpers
# ---------------------------------------------------------------------------


def _make_criterion_request(
    name: str = "Thesis",
    weight: Decimal = Decimal("50"),
    min_score: int = 1,
    max_score: int = 5,
) -> RubricCriterionRequest:
    return RubricCriterionRequest(
        name=name,
        weight=weight,
        min_score=min_score,
        max_score=max_score,
    )


def _make_criteria_100() -> list[RubricCriterionRequest]:
    """Two criteria that sum to exactly 100."""
    return [
        _make_criterion_request("Thesis", Decimal("60")),
        _make_criterion_request("Evidence", Decimal("40")),
    ]


def _make_rubric_orm(
    teacher_id: uuid.UUID | None = None,
    rubric_id: uuid.UUID | None = None,
    name: str = "Test Rubric",
) -> MagicMock:
    rubric = MagicMock()
    rubric.id = rubric_id or uuid.uuid4()
    rubric.teacher_id = teacher_id or uuid.uuid4()
    rubric.name = name
    rubric.description = None
    rubric.is_template = False
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
    c.description = "Does the essay have a clear thesis?"
    c.weight = Decimal("100")
    c.min_score = 1
    c.max_score = 5
    c.display_order = display_order
    c.anchor_descriptions = None
    return c


def _make_db() -> AsyncMock:
    db = AsyncMock()
    db.add = MagicMock()
    db.delete = AsyncMock()
    db.commit = AsyncMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    return db


# ---------------------------------------------------------------------------
# _validate_weight_sum
# ---------------------------------------------------------------------------


class TestValidateWeightSum:
    def test_valid_sum_exactly_100(self) -> None:
        criteria = _make_criteria_100()
        # Should not raise.
        _validate_weight_sum(criteria)

    def test_valid_single_criterion_100(self) -> None:
        criteria = [_make_criterion_request("Thesis", Decimal("100"))]
        _validate_weight_sum(criteria)

    def test_valid_three_criteria_sum_100(self) -> None:
        criteria = [
            _make_criterion_request("A", Decimal("33.33")),
            _make_criterion_request("B", Decimal("33.33")),
            _make_criterion_request("C", Decimal("33.34")),
        ]
        _validate_weight_sum(criteria)

    def test_invalid_sum_below_100(self) -> None:
        criteria = [
            _make_criterion_request("A", Decimal("49")),
            _make_criterion_request("B", Decimal("50")),
        ]
        with pytest.raises(RubricWeightInvalidError) as exc_info:
            _validate_weight_sum(criteria)
        assert "99" in str(exc_info.value)

    def test_invalid_sum_above_100(self) -> None:
        criteria = [
            _make_criterion_request("A", Decimal("60")),
            _make_criterion_request("B", Decimal("50")),
        ]
        with pytest.raises(RubricWeightInvalidError) as exc_info:
            _validate_weight_sum(criteria)
        assert "110" in str(exc_info.value)

    def test_raises_rubric_weight_invalid_error_type(self) -> None:
        criteria = [_make_criterion_request("A", Decimal("50"))]
        with pytest.raises(RubricWeightInvalidError):
            _validate_weight_sum(criteria)

    def test_error_has_criteria_field(self) -> None:
        criteria = [_make_criterion_request("A", Decimal("50"))]
        with pytest.raises(RubricWeightInvalidError) as exc_info:
            _validate_weight_sum(criteria)
        assert exc_info.value.field == "criteria"


# ---------------------------------------------------------------------------
# create_rubric
# ---------------------------------------------------------------------------


class TestCreateRubric:
    @pytest.mark.asyncio
    async def test_creates_rubric_successfully(self) -> None:
        teacher_id = uuid.uuid4()
        rubric_orm = _make_rubric_orm(teacher_id=teacher_id)
        criterion_orm = _make_criterion_orm(rubric_id=rubric_orm.id)

        db = _make_db()
        # First execute returns mock with scalar_one_or_none for rubric
        # (not needed for create — no prior SELECT needed)
        db.flush = AsyncMock(side_effect=lambda: setattr(rubric_orm, "id", rubric_orm.id))
        db.refresh = AsyncMock()

        with (
            patch("app.services.rubric.Rubric", return_value=rubric_orm),
            patch("app.services.rubric.RubricCriterion", return_value=criterion_orm),
        ):
            result_rubric, result_criteria = await create_rubric(
                db,
                teacher_id=teacher_id,
                name="Test Rubric",
                description=None,
                criteria_requests=_make_criteria_100(),
            )

        db.add.assert_called()
        db.commit.assert_called_once()
        db.refresh.assert_called_once_with(rubric_orm)
        assert result_rubric is rubric_orm

    @pytest.mark.asyncio
    async def test_raises_weight_invalid_error(self) -> None:
        db = _make_db()
        criteria = [_make_criterion_request("A", Decimal("50"))]  # does not sum to 100

        with pytest.raises(RubricWeightInvalidError):
            await create_rubric(
                db,
                teacher_id=uuid.uuid4(),
                name="Bad Rubric",
                description=None,
                criteria_requests=criteria,
            )

        # DB should not have been touched.
        db.add.assert_not_called()
        db.commit.assert_not_called()


# ---------------------------------------------------------------------------
# get_rubric
# ---------------------------------------------------------------------------


class TestGetRubric:
    @pytest.mark.asyncio
    async def test_returns_rubric_and_criteria(self) -> None:
        teacher_id = uuid.uuid4()
        rubric_id = uuid.uuid4()
        rubric_orm = _make_rubric_orm(teacher_id=teacher_id, rubric_id=rubric_id)
        criterion_orm = _make_criterion_orm(rubric_id=rubric_id)

        db = _make_db()
        rubric_result = MagicMock()
        rubric_result.scalar_one_or_none.return_value = rubric_orm
        criteria_result = MagicMock()
        criteria_result.scalars.return_value.all.return_value = [criterion_orm]
        db.execute = AsyncMock(side_effect=[rubric_result, criteria_result])

        result_rubric, result_criteria = await get_rubric(db, teacher_id, rubric_id)

        assert result_rubric is rubric_orm
        assert result_criteria == [criterion_orm]

    @pytest.mark.asyncio
    async def test_raises_not_found_when_missing(self) -> None:
        db = _make_db()
        rubric_result = MagicMock()
        rubric_result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=rubric_result)

        with pytest.raises(NotFoundError):
            await get_rubric(db, uuid.uuid4(), uuid.uuid4())

    @pytest.mark.asyncio
    async def test_raises_forbidden_for_cross_teacher(self) -> None:
        teacher_id = uuid.uuid4()
        other_teacher_id = uuid.uuid4()
        rubric_orm = _make_rubric_orm(teacher_id=other_teacher_id)

        db = _make_db()
        rubric_result = MagicMock()
        rubric_result.scalar_one_or_none.return_value = rubric_orm
        db.execute = AsyncMock(return_value=rubric_result)

        with pytest.raises(ForbiddenError):
            await get_rubric(db, teacher_id, rubric_orm.id)


# ---------------------------------------------------------------------------
# delete_rubric
# ---------------------------------------------------------------------------


class TestDeleteRubric:
    @pytest.mark.asyncio
    async def test_soft_deletes_rubric(self) -> None:
        teacher_id = uuid.uuid4()
        rubric_id = uuid.uuid4()
        rubric_orm = _make_rubric_orm(teacher_id=teacher_id, rubric_id=rubric_id)

        db = _make_db()
        rubric_result = MagicMock()
        rubric_result.scalar_one_or_none.return_value = rubric_orm
        in_use_result = MagicMock()
        in_use_result.scalar_one.return_value = 0  # not in use
        db.execute = AsyncMock(side_effect=[rubric_result, in_use_result])

        await delete_rubric(db, teacher_id, rubric_id)

        assert rubric_orm.deleted_at is not None
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_raises_in_use_error_when_open_assignment_exists(self) -> None:
        teacher_id = uuid.uuid4()
        rubric_id = uuid.uuid4()
        rubric_orm = _make_rubric_orm(teacher_id=teacher_id, rubric_id=rubric_id)

        db = _make_db()
        rubric_result = MagicMock()
        rubric_result.scalar_one_or_none.return_value = rubric_orm
        in_use_result = MagicMock()
        in_use_result.scalar_one.return_value = 1  # one open assignment
        db.execute = AsyncMock(side_effect=[rubric_result, in_use_result])

        with pytest.raises(RubricInUseError):
            await delete_rubric(db, teacher_id, rubric_id)

        db.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_raises_forbidden_for_cross_teacher(self) -> None:
        teacher_id = uuid.uuid4()
        rubric_orm = _make_rubric_orm(teacher_id=uuid.uuid4())  # different teacher

        db = _make_db()
        rubric_result = MagicMock()
        rubric_result.scalar_one_or_none.return_value = rubric_orm
        db.execute = AsyncMock(return_value=rubric_result)

        with pytest.raises(ForbiddenError):
            await delete_rubric(db, teacher_id, rubric_orm.id)


# ---------------------------------------------------------------------------
# duplicate_rubric
# ---------------------------------------------------------------------------


class TestDuplicateRubric:
    @pytest.mark.asyncio
    async def test_creates_copy_with_name_prefix(self) -> None:
        teacher_id = uuid.uuid4()
        rubric_id = uuid.uuid4()
        new_rubric_id = uuid.uuid4()
        source_rubric = _make_rubric_orm(
            teacher_id=teacher_id, rubric_id=rubric_id, name="My Rubric"
        )
        source_criterion = _make_criterion_orm(rubric_id=rubric_id)
        new_rubric = _make_rubric_orm(
            teacher_id=teacher_id, rubric_id=new_rubric_id, name="Copy of My Rubric"
        )

        db = _make_db()
        # After flush(), new_rubric.id is available; db.execute is called for
        # the criteria INSERT—no additional SELECT queries hit the real ORM
        # because we patch get_rubric to bypass the real SELECT.
        db.flush = AsyncMock()
        db.refresh = AsyncMock()

        # Patch get_rubric so duplicate_rubric doesn't call real SELECT queries.
        with patch(
            "app.services.rubric.get_rubric",
            new_callable=AsyncMock,
            return_value=(source_rubric, [source_criterion]),
        ):

            def _rubric_factory(**kwargs: object) -> MagicMock:
                new_rubric.name = str(kwargs.get("name", ""))
                return new_rubric

            with patch("app.services.rubric.Rubric", side_effect=_rubric_factory):
                result_rubric, _criteria = await duplicate_rubric(db, teacher_id, rubric_id)

        db.add.assert_called()
        db.commit.assert_called_once()
        assert result_rubric is new_rubric
        assert "Copy of" in result_rubric.name

    @pytest.mark.asyncio
    async def test_raises_not_found_for_missing_source(self) -> None:
        db = _make_db()

        with (
            patch(
                "app.services.rubric.get_rubric",
                new_callable=AsyncMock,
                side_effect=NotFoundError("Rubric not found."),
            ),
            pytest.raises(NotFoundError),
        ):
            await duplicate_rubric(db, uuid.uuid4(), uuid.uuid4())


# ---------------------------------------------------------------------------
# build_rubric_snapshot
# ---------------------------------------------------------------------------


class TestBuildRubricSnapshot:
    def test_snapshot_structure(self) -> None:
        teacher_id = uuid.uuid4()
        rubric = _make_rubric_orm(teacher_id=teacher_id)
        rubric.name = "Essay Rubric"
        rubric.description = "For 5-paragraph essays"

        criterion = _make_criterion_orm(rubric_id=rubric.id)
        criterion.name = "Thesis"
        criterion.description = "Clear thesis statement"
        criterion.weight = Decimal("100")
        criterion.min_score = 1
        criterion.max_score = 5
        criterion.display_order = 0
        criterion.anchor_descriptions = {"1": "No thesis", "5": "Precise thesis"}

        snapshot = build_rubric_snapshot(rubric, [criterion])

        assert snapshot["id"] == str(rubric.id)
        assert snapshot["name"] == "Essay Rubric"
        assert snapshot["description"] == "For 5-paragraph essays"
        criteria_list = snapshot["criteria"]
        assert isinstance(criteria_list, list)
        assert len(criteria_list) == 1
        c = criteria_list[0]  # type: ignore[index]
        assert c["name"] == "Thesis"  # type: ignore[index]
        assert c["weight"] == 100.0  # type: ignore[index]
        assert c["anchor_descriptions"] == {"1": "No thesis", "5": "Precise thesis"}  # type: ignore[index]

    def test_snapshot_with_no_criteria(self) -> None:
        rubric = _make_rubric_orm()
        snapshot = build_rubric_snapshot(rubric, [])
        assert snapshot["criteria"] == []

    def test_snapshot_description_none(self) -> None:
        rubric = _make_rubric_orm()
        rubric.description = None
        snapshot = build_rubric_snapshot(rubric, [])
        assert snapshot["description"] is None
