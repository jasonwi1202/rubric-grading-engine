"""Unit tests for app/services/assignment.py.

Tests cover:
- _validate_transition: all valid transitions and all invalid transitions
- create_assignment: rubric snapshot written at creation, rubric not owned → 403
- get_assignment: success, not-found, cross-teacher
- update_assignment: status transitions, field updates
- list_assignments: success and class not owned → 403

No real PostgreSQL.  All DB calls are mocked.  No student PII in fixtures.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.exceptions import ForbiddenError, InvalidStateTransitionError, NotFoundError
from app.models.assignment import AssignmentStatus
from app.services.assignment import (
    _validate_transition,  # noqa: PLC2701 — testing internal helper
    create_assignment,
    get_assignment,
    list_assignments,
    update_assignment,
)

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _make_teacher_id() -> uuid.UUID:
    return uuid.uuid4()


def _make_assignment_orm(
    teacher_id: uuid.UUID | None = None,
    assignment_id: uuid.UUID | None = None,
    class_id: uuid.UUID | None = None,
    rubric_id: uuid.UUID | None = None,
    status: AssignmentStatus = AssignmentStatus.draft,
    title: str = "Test Assignment",
    prompt: str | None = None,
    due_date: date | None = None,
) -> MagicMock:
    a = MagicMock()
    a.id = assignment_id or uuid.uuid4()
    a.class_id = class_id or uuid.uuid4()
    a.rubric_id = rubric_id or uuid.uuid4()
    a.title = title
    a.prompt = prompt
    a.due_date = due_date
    a.status = status
    a.rubric_snapshot = {"id": str(a.rubric_id), "name": "Test Rubric", "criteria": []}
    a.resubmission_enabled = False
    a.resubmission_limit = None
    return a


def _make_ownership_row(teacher_id: uuid.UUID, resource_id: uuid.UUID) -> MagicMock:
    """Generic ownership row mock (class, rubric, or any resource)."""
    row = MagicMock()
    row.id = resource_id
    row.teacher_id = teacher_id
    return row


def _make_assignment_ownership_row(teacher_id: uuid.UUID, assignment_id: uuid.UUID) -> MagicMock:
    row = MagicMock()
    row.id = assignment_id
    row.teacher_id = teacher_id
    return row


def _make_rubric_orm(teacher_id: uuid.UUID, rubric_id: uuid.UUID | None = None) -> MagicMock:
    rubric = MagicMock()
    rubric.id = rubric_id or uuid.uuid4()
    rubric.teacher_id = teacher_id
    rubric.name = "Test Rubric"
    rubric.description = None
    rubric.deleted_at = None
    return rubric


def _make_criterion_orm(rubric_id: uuid.UUID) -> MagicMock:
    c = MagicMock()
    c.id = uuid.uuid4()
    c.rubric_id = rubric_id
    c.name = "Thesis"
    c.description = "Argument quality"
    c.weight = Decimal("100")
    c.min_score = 1
    c.max_score = 5
    c.display_order = 0
    c.anchor_descriptions = None
    return c


def _make_db() -> AsyncMock:
    """Return an AsyncMock shaped like an AsyncSession.

    SQLAlchemy's ``add``/``delete`` are synchronous; ``execute``, ``commit``,
    and ``refresh`` are async.  Using plain ``AsyncMock()`` for the session
    makes ``add`` an ``AsyncMock`` too, which produces un-awaited-coroutine
    warnings and misrepresents the real API.  This helper corrects that.
    """
    db = AsyncMock()
    db.add = MagicMock()
    db.delete = MagicMock()
    return db


# ---------------------------------------------------------------------------
# _validate_transition
# ---------------------------------------------------------------------------


class TestValidateTransition:
    def test_draft_to_open_is_valid(self) -> None:
        _validate_transition(AssignmentStatus.draft, AssignmentStatus.open)  # no exception

    def test_open_to_grading_is_valid(self) -> None:
        _validate_transition(AssignmentStatus.open, AssignmentStatus.grading)

    def test_grading_to_review_is_valid(self) -> None:
        _validate_transition(AssignmentStatus.grading, AssignmentStatus.review)

    def test_review_to_complete_is_valid(self) -> None:
        _validate_transition(AssignmentStatus.review, AssignmentStatus.complete)

    def test_complete_to_returned_is_valid(self) -> None:
        _validate_transition(AssignmentStatus.complete, AssignmentStatus.returned)

    def test_same_status_raises(self) -> None:
        with pytest.raises(InvalidStateTransitionError):
            _validate_transition(AssignmentStatus.draft, AssignmentStatus.draft)

    def test_backward_transition_raises(self) -> None:
        with pytest.raises(InvalidStateTransitionError):
            _validate_transition(AssignmentStatus.open, AssignmentStatus.draft)

    def test_skip_transition_raises(self) -> None:
        """draft → grading skips a step and must be rejected."""
        with pytest.raises(InvalidStateTransitionError):
            _validate_transition(AssignmentStatus.draft, AssignmentStatus.grading)

    def test_terminal_status_raises(self) -> None:
        """returned is the terminal status — no further transitions are valid."""
        with pytest.raises(InvalidStateTransitionError):
            _validate_transition(AssignmentStatus.returned, AssignmentStatus.complete)

    def test_error_includes_field_status(self) -> None:
        with pytest.raises(InvalidStateTransitionError) as exc_info:
            _validate_transition(AssignmentStatus.draft, AssignmentStatus.review)
        assert exc_info.value.field == "status"


# ---------------------------------------------------------------------------
# create_assignment — rubric snapshot
# ---------------------------------------------------------------------------


class TestCreateAssignment:
    @pytest.mark.asyncio
    async def test_snapshot_written_at_creation(self) -> None:
        """rubric_snapshot must be set from the live rubric at creation time."""
        teacher_id = _make_teacher_id()
        class_id = uuid.uuid4()
        rubric = _make_rubric_orm(teacher_id)
        criterion = _make_criterion_orm(rubric.id)

        db = _make_db()

        # Class ownership query
        class_ownership_result = MagicMock()
        class_ownership_result.one_or_none.return_value = _make_ownership_row(teacher_id, class_id)

        # Full class fetch
        class_full_result = MagicMock()
        class_full_result.scalar_one_or_none.return_value = MagicMock(
            id=class_id, teacher_id=teacher_id
        )

        # Rubric ownership query
        rubric_ownership_result = MagicMock()
        rubric_ownership_result.one_or_none.return_value = _make_ownership_row(
            teacher_id, rubric.id
        )

        # Full rubric fetch
        rubric_full_result = MagicMock()
        rubric_full_result.scalar_one.return_value = rubric

        # Criteria fetch
        criteria_result = MagicMock()
        criteria_result.scalars.return_value.all.return_value = [criterion]

        db.execute.side_effect = [
            class_ownership_result,
            class_full_result,
            rubric_ownership_result,
            rubric_full_result,
            criteria_result,
        ]

        # Simulate commit + refresh setting snapshot on the assignment object
        created_assignment = _make_assignment_orm(
            teacher_id=teacher_id,
            class_id=class_id,
            rubric_id=rubric.id,
        )

        async def fake_refresh(obj: object) -> None:
            obj.rubric_snapshot = {  # type: ignore[union-attr]
                "id": str(rubric.id),
                "name": rubric.name,
                "description": rubric.description,
                "criteria": [
                    {
                        "id": str(criterion.id),
                        "name": criterion.name,
                        "description": criterion.description,
                        "weight": float(criterion.weight),
                        "min_score": criterion.min_score,
                        "max_score": criterion.max_score,
                        "display_order": criterion.display_order,
                        "anchor_descriptions": criterion.anchor_descriptions,
                    }
                ],
            }

        db.refresh = fake_refresh

        with patch("app.services.assignment.Assignment", return_value=created_assignment):
            result = await create_assignment(
                db,
                teacher_id=teacher_id,
                class_id=class_id,
                rubric_id=rubric.id,
                title="Essay Assignment",
                prompt=None,
                due_date=None,
            )

        assert result.rubric_snapshot is not None, "rubric_snapshot must be set"
        assert result.rubric_snapshot["id"] == str(rubric.id)
        assert len(result.rubric_snapshot["criteria"]) == 1

    @pytest.mark.asyncio
    async def test_cross_teacher_rubric_raises_403(self) -> None:
        """Rubric belonging to a different teacher raises ForbiddenError."""
        teacher_id = _make_teacher_id()
        other_teacher_id = uuid.uuid4()
        class_id = uuid.uuid4()
        rubric_id = uuid.uuid4()

        db = _make_db()

        class_ownership_result = MagicMock()
        class_ownership_result.one_or_none.return_value = _make_ownership_row(teacher_id, class_id)

        class_full_result = MagicMock()
        class_full_result.scalar_one_or_none.return_value = MagicMock(
            id=class_id, teacher_id=teacher_id
        )

        # Rubric belongs to a different teacher
        rubric_ownership_result = MagicMock()
        rubric_ownership_result.one_or_none.return_value = _make_ownership_row(
            other_teacher_id, rubric_id
        )

        db.execute.side_effect = [
            class_ownership_result,
            class_full_result,
            rubric_ownership_result,
        ]

        with pytest.raises(ForbiddenError):
            await create_assignment(
                db,
                teacher_id=teacher_id,
                class_id=class_id,
                rubric_id=rubric_id,
                title="Test",
                prompt=None,
                due_date=None,
            )

    @pytest.mark.asyncio
    async def test_class_not_found_raises_404(self) -> None:
        db = _make_db()
        result = MagicMock()
        result.one_or_none.return_value = None
        db.execute.return_value = result

        with pytest.raises(NotFoundError):
            await create_assignment(
                db,
                teacher_id=uuid.uuid4(),
                class_id=uuid.uuid4(),
                rubric_id=uuid.uuid4(),
                title="Test",
                prompt=None,
                due_date=None,
            )

    @pytest.mark.asyncio
    async def test_cross_teacher_class_raises_403(self) -> None:
        teacher_id = _make_teacher_id()
        other_teacher_id = uuid.uuid4()
        class_id = uuid.uuid4()

        db = _make_db()
        result = MagicMock()
        row = MagicMock()
        row.teacher_id = other_teacher_id
        result.one_or_none.return_value = row
        db.execute.return_value = result

        with pytest.raises(ForbiddenError):
            await create_assignment(
                db,
                teacher_id=teacher_id,
                class_id=class_id,
                rubric_id=uuid.uuid4(),
                title="Test",
                prompt=None,
                due_date=None,
            )


# ---------------------------------------------------------------------------
# get_assignment
# ---------------------------------------------------------------------------


class TestGetAssignment:
    @pytest.mark.asyncio
    async def test_returns_assignment(self) -> None:
        teacher_id = _make_teacher_id()
        assignment = _make_assignment_orm()

        db = _make_db()
        ownership_result = MagicMock()
        ownership_result.one_or_none.return_value = _make_assignment_ownership_row(
            teacher_id, assignment.id
        )
        full_result = MagicMock()
        full_result.scalar_one_or_none.return_value = assignment
        db.execute.side_effect = [ownership_result, full_result]

        result = await get_assignment(db, teacher_id, assignment.id)
        assert result.id == assignment.id

    @pytest.mark.asyncio
    async def test_not_found_raises_404(self) -> None:
        db = _make_db()
        result = MagicMock()
        result.one_or_none.return_value = None
        db.execute.return_value = result

        with pytest.raises(NotFoundError):
            await get_assignment(db, uuid.uuid4(), uuid.uuid4())

    @pytest.mark.asyncio
    async def test_cross_teacher_raises_403(self) -> None:
        teacher_id = _make_teacher_id()
        other_teacher_id = uuid.uuid4()
        assignment_id = uuid.uuid4()

        db = _make_db()
        result = MagicMock()
        row = MagicMock()
        row.teacher_id = other_teacher_id
        result.one_or_none.return_value = row
        db.execute.return_value = result

        with pytest.raises(ForbiddenError):
            await get_assignment(db, teacher_id, assignment_id)


# ---------------------------------------------------------------------------
# update_assignment — state machine
# ---------------------------------------------------------------------------


class TestUpdateAssignment:
    def _make_db_with_assignment(self, teacher_id: uuid.UUID, assignment: MagicMock) -> AsyncMock:
        db = _make_db()
        ownership_result = MagicMock()
        ownership_result.one_or_none.return_value = _make_assignment_ownership_row(
            teacher_id, assignment.id
        )
        full_result = MagicMock()
        full_result.scalar_one_or_none.return_value = assignment
        db.execute.side_effect = [ownership_result, full_result]
        db.refresh = AsyncMock()
        return db

    @pytest.mark.asyncio
    async def test_valid_status_transition_draft_to_open(self) -> None:
        teacher_id = _make_teacher_id()
        assignment = _make_assignment_orm(status=AssignmentStatus.draft)
        db = self._make_db_with_assignment(teacher_id, assignment)

        result = await update_assignment(
            db,
            teacher_id=teacher_id,
            assignment_id=assignment.id,
            title=None,
            prompt=None,
            update_prompt=False,
            due_date=None,
            update_due_date=False,
            status=AssignmentStatus.open,
        )
        assert result.status == AssignmentStatus.open

    @pytest.mark.asyncio
    async def test_invalid_status_transition_raises_422(self) -> None:
        teacher_id = _make_teacher_id()
        assignment = _make_assignment_orm(status=AssignmentStatus.draft)
        db = self._make_db_with_assignment(teacher_id, assignment)

        with pytest.raises(InvalidStateTransitionError):
            await update_assignment(
                db,
                teacher_id=teacher_id,
                assignment_id=assignment.id,
                title=None,
                prompt=None,
                update_prompt=False,
                due_date=None,
                update_due_date=False,
                status=AssignmentStatus.grading,  # skip a step
            )

    @pytest.mark.asyncio
    async def test_update_title(self) -> None:
        teacher_id = _make_teacher_id()
        assignment = _make_assignment_orm(status=AssignmentStatus.draft, title="Old")
        db = self._make_db_with_assignment(teacher_id, assignment)

        result = await update_assignment(
            db,
            teacher_id=teacher_id,
            assignment_id=assignment.id,
            title="New Title",
            prompt=None,
            update_prompt=False,
            due_date=None,
            update_due_date=False,
            status=None,
        )
        assert result.title == "New Title"

    @pytest.mark.asyncio
    async def test_update_prompt_clears_when_none(self) -> None:
        teacher_id = _make_teacher_id()
        assignment = _make_assignment_orm(prompt="Old prompt")
        db = self._make_db_with_assignment(teacher_id, assignment)

        result = await update_assignment(
            db,
            teacher_id=teacher_id,
            assignment_id=assignment.id,
            title=None,
            prompt=None,
            update_prompt=True,  # explicitly clearing
            due_date=None,
            update_due_date=False,
            status=None,
        )
        assert result.prompt is None

    @pytest.mark.asyncio
    async def test_cross_teacher_raises_403(self) -> None:
        teacher_id = _make_teacher_id()
        other_teacher_id = uuid.uuid4()
        assignment_id = uuid.uuid4()

        db = _make_db()
        result = MagicMock()
        row = MagicMock()
        row.teacher_id = other_teacher_id
        result.one_or_none.return_value = row
        db.execute.return_value = result

        with pytest.raises(ForbiddenError):
            await update_assignment(
                db,
                teacher_id=teacher_id,
                assignment_id=assignment_id,
                title=None,
                prompt=None,
                update_prompt=False,
                due_date=None,
                update_due_date=False,
                status=None,
            )


# ---------------------------------------------------------------------------
# list_assignments
# ---------------------------------------------------------------------------


class TestListAssignments:
    @pytest.mark.asyncio
    async def test_returns_assignments_for_class(self) -> None:
        teacher_id = _make_teacher_id()
        class_id = uuid.uuid4()
        a1 = _make_assignment_orm(class_id=class_id)
        a2 = _make_assignment_orm(class_id=class_id)

        db = _make_db()
        # Class ownership
        class_ownership_result = MagicMock()
        class_ownership_result.one_or_none.return_value = _make_ownership_row(teacher_id, class_id)
        # Full class
        class_full_result = MagicMock()
        class_full_result.scalar_one_or_none.return_value = MagicMock(
            id=class_id, teacher_id=teacher_id
        )
        # Assignment list
        assignment_list_result = MagicMock()
        assignment_list_result.scalars.return_value.all.return_value = [a1, a2]
        db.execute.side_effect = [
            class_ownership_result,
            class_full_result,
            assignment_list_result,
        ]

        results = await list_assignments(db, teacher_id=teacher_id, class_id=class_id)
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_cross_teacher_class_raises_403(self) -> None:
        teacher_id = _make_teacher_id()
        other_teacher_id = uuid.uuid4()
        class_id = uuid.uuid4()

        db = _make_db()
        result = MagicMock()
        row = MagicMock()
        row.teacher_id = other_teacher_id
        result.one_or_none.return_value = row
        db.execute.return_value = result

        with pytest.raises(ForbiddenError):
            await list_assignments(db, teacher_id=teacher_id, class_id=class_id)
