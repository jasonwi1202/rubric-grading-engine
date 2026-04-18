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
    list_rubrics,
    update_rubric,
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


def _make_ownership_result(teacher_id: uuid.UUID) -> MagicMock:
    """Mock for the first query in _get_rubric_owned_by (id + teacher_id columns)."""
    row = MagicMock()
    row.teacher_id = teacher_id
    result = MagicMock()
    result.one_or_none.return_value = row
    return result


def _make_not_found_ownership_result() -> MagicMock:
    """Mock for the first query returning no row (rubric not found)."""
    result = MagicMock()
    result.one_or_none.return_value = None
    return result


def _make_db() -> AsyncMock:
    db = AsyncMock()
    db.add = MagicMock()
    db.delete = MagicMock()
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
        # Query 1: ownership check (id + teacher_id)
        ownership_result = _make_ownership_result(teacher_id)
        # Query 2: full rubric row
        rubric_result = MagicMock()
        rubric_result.scalar_one_or_none.return_value = rubric_orm
        # Query 3: criteria
        criteria_result = MagicMock()
        criteria_result.scalars.return_value.all.return_value = [criterion_orm]
        db.execute = AsyncMock(side_effect=[ownership_result, rubric_result, criteria_result])

        result_rubric, result_criteria = await get_rubric(db, teacher_id, rubric_id)

        assert result_rubric is rubric_orm
        assert result_criteria == [criterion_orm]

    @pytest.mark.asyncio
    async def test_raises_not_found_when_missing(self) -> None:
        db = _make_db()
        db.execute = AsyncMock(return_value=_make_not_found_ownership_result())

        with pytest.raises(NotFoundError):
            await get_rubric(db, uuid.uuid4(), uuid.uuid4())

    @pytest.mark.asyncio
    async def test_raises_not_found_when_deleted_between_queries(self) -> None:
        """Rubric deleted between ownership check and full-row fetch → NotFoundError."""
        teacher_id = uuid.uuid4()
        rubric_id = uuid.uuid4()

        db = _make_db()
        # First query succeeds (ownership check passes).
        ownership_result = _make_ownership_result(teacher_id)
        # Second query returns None (rubric was deleted between queries).
        toctou_result = MagicMock()
        toctou_result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(side_effect=[ownership_result, toctou_result])

        with pytest.raises(NotFoundError):
            await get_rubric(db, teacher_id, rubric_id)

    @pytest.mark.asyncio
    async def test_raises_forbidden_for_cross_teacher(self) -> None:
        teacher_id = uuid.uuid4()
        other_teacher_id = uuid.uuid4()
        rubric_orm = _make_rubric_orm(teacher_id=other_teacher_id)

        db = _make_db()
        # Ownership row has a different teacher_id — triggers ForbiddenError.
        db.execute = AsyncMock(return_value=_make_ownership_result(other_teacher_id))

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
        ownership_result = _make_ownership_result(teacher_id)
        rubric_result = MagicMock()
        rubric_result.scalar_one_or_none.return_value = rubric_orm
        in_use_result = MagicMock()
        in_use_result.scalar_one.return_value = 0  # not in use
        db.execute = AsyncMock(side_effect=[ownership_result, rubric_result, in_use_result])

        await delete_rubric(db, teacher_id, rubric_id)

        assert rubric_orm.deleted_at is not None
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_raises_in_use_error_when_open_assignment_exists(self) -> None:
        teacher_id = uuid.uuid4()
        rubric_id = uuid.uuid4()
        rubric_orm = _make_rubric_orm(teacher_id=teacher_id, rubric_id=rubric_id)

        db = _make_db()
        ownership_result = _make_ownership_result(teacher_id)
        rubric_result = MagicMock()
        rubric_result.scalar_one_or_none.return_value = rubric_orm
        in_use_result = MagicMock()
        in_use_result.scalar_one.return_value = 1  # one open assignment
        db.execute = AsyncMock(side_effect=[ownership_result, rubric_result, in_use_result])

        with pytest.raises(RubricInUseError):
            await delete_rubric(db, teacher_id, rubric_id)

        db.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_raises_forbidden_for_cross_teacher(self) -> None:
        teacher_id = uuid.uuid4()
        other_teacher_id = uuid.uuid4()

        db = _make_db()
        db.execute = AsyncMock(return_value=_make_ownership_result(other_teacher_id))

        with pytest.raises(ForbiddenError):
            await delete_rubric(db, teacher_id, uuid.uuid4())


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


# ---------------------------------------------------------------------------
# list_rubrics
# ---------------------------------------------------------------------------


class TestListRubrics:
    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_rubrics(self) -> None:
        db = _make_db()
        rubric_result = MagicMock()
        rubric_result.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(return_value=rubric_result)

        result = await list_rubrics(db, uuid.uuid4())

        assert result == []
        # Only one query (rubrics); criteria query is skipped when empty.
        db.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_returns_rubrics_with_criteria(self) -> None:
        teacher_id = uuid.uuid4()
        rubric_a = _make_rubric_orm(teacher_id=teacher_id)
        rubric_b = _make_rubric_orm(teacher_id=teacher_id)
        criterion_a1 = _make_criterion_orm(rubric_id=rubric_a.id)
        criterion_a2 = _make_criterion_orm(rubric_id=rubric_a.id, display_order=1)
        criterion_b1 = _make_criterion_orm(rubric_id=rubric_b.id)

        db = _make_db()
        rubric_result = MagicMock()
        rubric_result.scalars.return_value.all.return_value = [rubric_a, rubric_b]
        criteria_result = MagicMock()
        criteria_result.scalars.return_value.all.return_value = [
            criterion_a1,
            criterion_a2,
            criterion_b1,
        ]
        db.execute = AsyncMock(side_effect=[rubric_result, criteria_result])

        result = await list_rubrics(db, teacher_id)

        assert len(result) == 2
        # rubric_a should have 2 criteria, rubric_b should have 1
        a_criteria = next(c for r, c in result if r.id == rubric_a.id)
        b_criteria = next(c for r, c in result if r.id == rubric_b.id)
        assert len(a_criteria) == 2
        assert len(b_criteria) == 1

    @pytest.mark.asyncio
    async def test_rubric_with_no_criteria_gets_empty_list(self) -> None:
        teacher_id = uuid.uuid4()
        rubric = _make_rubric_orm(teacher_id=teacher_id)

        db = _make_db()
        rubric_result = MagicMock()
        rubric_result.scalars.return_value.all.return_value = [rubric]
        criteria_result = MagicMock()
        criteria_result.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(side_effect=[rubric_result, criteria_result])

        result = await list_rubrics(db, teacher_id)

        assert len(result) == 1
        _, criteria = result[0]
        assert criteria == []


# ---------------------------------------------------------------------------
# update_rubric
# ---------------------------------------------------------------------------


class TestUpdateRubric:
    @pytest.mark.asyncio
    async def test_updates_name(self) -> None:
        teacher_id = uuid.uuid4()
        rubric_id = uuid.uuid4()
        rubric_orm = _make_rubric_orm(teacher_id=teacher_id, rubric_id=rubric_id)
        criterion_orm = _make_criterion_orm(rubric_id=rubric_id)

        db = _make_db()
        ownership_result = _make_ownership_result(teacher_id)
        rubric_result = MagicMock()
        rubric_result.scalar_one_or_none.return_value = rubric_orm
        criteria_result = MagicMock()
        criteria_result.scalars.return_value.all.return_value = [criterion_orm]
        db.execute = AsyncMock(side_effect=[ownership_result, rubric_result, criteria_result])

        result_rubric, result_criteria = await update_rubric(
            db,
            teacher_id=teacher_id,
            rubric_id=rubric_id,
            name="New Name",
            description=None,
            update_description=False,
            criteria_requests=None,
        )

        assert rubric_orm.name == "New Name"
        db.commit.assert_called_once()
        assert result_rubric is rubric_orm
        assert result_criteria == [criterion_orm]

    @pytest.mark.asyncio
    async def test_updates_description_when_flag_true(self) -> None:
        teacher_id = uuid.uuid4()
        rubric_id = uuid.uuid4()
        rubric_orm = _make_rubric_orm(teacher_id=teacher_id, rubric_id=rubric_id)

        db = _make_db()
        ownership_result = _make_ownership_result(teacher_id)
        rubric_result = MagicMock()
        rubric_result.scalar_one_or_none.return_value = rubric_orm
        criteria_result = MagicMock()
        criteria_result.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(side_effect=[ownership_result, rubric_result, criteria_result])

        await update_rubric(
            db,
            teacher_id=teacher_id,
            rubric_id=rubric_id,
            name=None,
            description="New description",
            update_description=True,
            criteria_requests=None,
        )

        assert rubric_orm.description == "New description"

    @pytest.mark.asyncio
    async def test_does_not_update_description_when_flag_false(self) -> None:
        teacher_id = uuid.uuid4()
        rubric_id = uuid.uuid4()
        rubric_orm = _make_rubric_orm(teacher_id=teacher_id, rubric_id=rubric_id)
        rubric_orm.description = "Original"

        db = _make_db()
        ownership_result = _make_ownership_result(teacher_id)
        rubric_result = MagicMock()
        rubric_result.scalar_one_or_none.return_value = rubric_orm
        criteria_result = MagicMock()
        criteria_result.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(side_effect=[ownership_result, rubric_result, criteria_result])

        await update_rubric(
            db,
            teacher_id=teacher_id,
            rubric_id=rubric_id,
            name=None,
            description=None,
            update_description=False,
            criteria_requests=None,
        )

        assert rubric_orm.description == "Original"

    @pytest.mark.asyncio
    async def test_replaces_criteria_when_provided(self) -> None:
        teacher_id = uuid.uuid4()
        rubric_id = uuid.uuid4()
        rubric_orm = _make_rubric_orm(teacher_id=teacher_id, rubric_id=rubric_id)
        old_criterion = _make_criterion_orm(rubric_id=rubric_id)

        new_criteria_requests = _make_criteria_100()

        db = _make_db()
        ownership_result = _make_ownership_result(teacher_id)
        rubric_result = MagicMock()
        rubric_result.scalar_one_or_none.return_value = rubric_orm
        # Criteria query (to fetch existing for deletion)
        existing_criteria_result = MagicMock()
        existing_criteria_result.scalars.return_value.all.return_value = [old_criterion]
        db.execute = AsyncMock(
            side_effect=[ownership_result, rubric_result, existing_criteria_result]
        )

        result_rubric, result_criteria = await update_rubric(
            db,
            teacher_id=teacher_id,
            rubric_id=rubric_id,
            name=None,
            description=None,
            update_description=False,
            criteria_requests=new_criteria_requests,
        )

        # Old criterion should have been deleted.
        db.delete.assert_called_once_with(old_criterion)
        db.flush.assert_called_once()
        db.add.assert_called()
        db.commit.assert_called_once()
        # New criteria returned (2 criteria from _make_criteria_100).
        assert len(result_criteria) == 2

    @pytest.mark.asyncio
    async def test_raises_weight_invalid_when_new_criteria_bad(self) -> None:
        teacher_id = uuid.uuid4()
        rubric_id = uuid.uuid4()
        rubric_orm = _make_rubric_orm(teacher_id=teacher_id, rubric_id=rubric_id)

        db = _make_db()
        ownership_result = _make_ownership_result(teacher_id)
        rubric_result = MagicMock()
        rubric_result.scalar_one_or_none.return_value = rubric_orm
        db.execute = AsyncMock(side_effect=[ownership_result, rubric_result])

        bad_criteria = [_make_criterion_request("A", Decimal("50"))]

        with pytest.raises(RubricWeightInvalidError):
            await update_rubric(
                db,
                teacher_id=teacher_id,
                rubric_id=rubric_id,
                name=None,
                description=None,
                update_description=False,
                criteria_requests=bad_criteria,
            )

        db.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_raises_forbidden_for_cross_teacher(self) -> None:
        teacher_id = uuid.uuid4()
        other_teacher_id = uuid.uuid4()

        db = _make_db()
        db.execute = AsyncMock(return_value=_make_ownership_result(other_teacher_id))

        with pytest.raises(ForbiddenError):
            await update_rubric(
                db,
                teacher_id=teacher_id,
                rubric_id=uuid.uuid4(),
                name="Hacked",
                description=None,
                update_description=False,
                criteria_requests=None,
            )
