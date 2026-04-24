"""Unit tests for app/services/regrade_request.py.

All database calls are mocked — no real PostgreSQL.
No student PII in any fixture.

Coverage:
- create_regrade_request: happy path, window enforcement, limit enforcement,
  cross-teacher access returns ForbiddenError, criterion_score_id ownership check.
- list_regrade_requests_for_assignment: happy path, cross-teacher returns ForbiddenError.
- resolve_regrade_request: approve happy path, deny happy path,
  deny without note raises ValidationError, cross-teacher returns ForbiddenError,
  already-resolved raises ConflictError, criterion score not found raises NotFoundError,
  grade locked raises GradeLockedError, new score without criterion raises ValidationError.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.exceptions import (
    ConflictError,
    ForbiddenError,
    GradeLockedError,
    NotFoundError,
    RegradeRequestLimitReachedError,
    RegradeWindowClosedError,
    ValidationError,
)
from app.models.grade import ConfidenceLevel, StrictnessLevel
from app.models.regrade_request import RegradeRequestStatus
from app.schemas.regrade_request import RegradeRequestCreate, RegradeRequestResolveRequest
from app.services.regrade_request import (
    create_regrade_request,
    list_regrade_requests_for_assignment,
    resolve_regrade_request,
)

# ---------------------------------------------------------------------------
# Helpers / factories
# ---------------------------------------------------------------------------


def _make_uuid() -> uuid.UUID:
    return uuid.uuid4()


def _make_grade(
    grade_id: uuid.UUID | None = None,
    created_at: datetime | None = None,
) -> MagicMock:
    g = MagicMock()
    g.id = grade_id or _make_uuid()
    g.essay_version_id = _make_uuid()
    g.total_score = Decimal("3")
    g.max_possible_score = Decimal("5")
    g.summary_feedback = "AI-generated summary."
    g.summary_feedback_edited = None
    g.strictness = StrictnessLevel.balanced
    g.ai_model = "gpt-4o"
    g.prompt_version = "grading-v1"
    g.is_locked = False
    g.locked_at = None
    g.overall_confidence = ConfidenceLevel.high
    g.created_at = created_at or datetime.now(UTC)
    return g


def _make_regrade_request(
    request_id: uuid.UUID | None = None,
    grade_id: uuid.UUID | None = None,
    teacher_id: uuid.UUID | None = None,
    status: RegradeRequestStatus = RegradeRequestStatus.open,
    criterion_score_id: uuid.UUID | None = None,
) -> MagicMock:
    r = MagicMock()
    r.id = request_id or _make_uuid()
    r.grade_id = grade_id or _make_uuid()
    r.criterion_score_id = criterion_score_id
    r.teacher_id = teacher_id or _make_uuid()
    r.dispute_text = "The score does not reflect the quality of the argument."
    r.status = status
    r.resolution_note = None
    r.resolved_at = None
    r.created_at = datetime.now(UTC)
    return r


def _make_criterion_score(
    grade_id: uuid.UUID | None = None,
    cs_id: uuid.UUID | None = None,
) -> MagicMock:
    cs = MagicMock()
    cs.id = cs_id or _make_uuid()
    cs.grade_id = grade_id or _make_uuid()
    cs.rubric_criterion_id = _make_uuid()
    cs.ai_score = 3
    cs.teacher_score = None
    cs.final_score = 3
    cs.ai_justification = "Justification text."
    cs.ai_feedback = "AI feedback."
    cs.teacher_feedback = None
    cs.confidence = ConfidenceLevel.high
    cs.created_at = datetime.now(UTC)
    return cs


# ---------------------------------------------------------------------------
# DB mock helpers (mirrors pattern from test_grade_service.py)
# ---------------------------------------------------------------------------


def _scalars_mock(items: list) -> MagicMock:
    result = MagicMock()
    scalars = MagicMock()
    scalars.all = MagicMock(return_value=items)
    result.scalars = MagicMock(return_value=scalars)
    return result


def _scalar_one_or_none_mock(value: object) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=value)
    return result


def _scalar_one_mock(value: object) -> MagicMock:
    result = MagicMock()
    result.scalar_one = MagicMock(return_value=value)
    return result


# ---------------------------------------------------------------------------
# Tests — create_regrade_request
# ---------------------------------------------------------------------------


class TestCreateRegradeRequest:
    """Tests for create_regrade_request service function."""

    @pytest.mark.asyncio
    async def test_happy_path_creates_request(self) -> None:
        """Returns a RegradeRequestResponse on success within the window."""
        teacher_id = _make_uuid()
        grade = _make_grade(created_at=datetime.now(UTC))
        db = AsyncMock()
        db.add = MagicMock()
        db.execute = AsyncMock(
            side_effect=[
                _scalar_one_or_none_mock(grade),  # tenant-scoped grade load
                _scalar_one_mock(0),               # count of existing requests
                # no criterion_score_id, so no CS ownership check
            ]
        )

        def _refresh_regrade_request(obj: object) -> None:
            """Simulate db.refresh() for a newly created RegradeRequest."""
            rr_stub = _make_regrade_request(grade_id=grade.id, teacher_id=teacher_id)
            obj.id = rr_stub.id  # type: ignore[attr-defined]
            obj.created_at = rr_stub.created_at  # type: ignore[attr-defined]
            obj.status = RegradeRequestStatus.open  # type: ignore[attr-defined]
            obj.criterion_score_id = None  # type: ignore[attr-defined]
            obj.resolution_note = None  # type: ignore[attr-defined]
            obj.resolved_at = None  # type: ignore[attr-defined]

        db.refresh = AsyncMock(side_effect=_refresh_regrade_request)

        body = RegradeRequestCreate(dispute_text="Score seems too low.")

        with patch("app.services.regrade_request.settings") as mock_settings:
            mock_settings.regrade_window_days = 7
            mock_settings.regrade_max_per_grade = 1
            response = await create_regrade_request(db, grade.id, teacher_id, body)

        assert response.grade_id == grade.id
        assert response.teacher_id == teacher_id
        db.add.assert_called_once()
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_window_expired_raises_window_closed(self) -> None:
        """Raises RegradeWindowClosedError when the grade was created more than REGRADE_WINDOW_DAYS ago."""
        teacher_id = _make_uuid()
        # Grade created 10 days ago; window is 7 days.
        old_created_at = datetime.now(UTC) - timedelta(days=10)
        grade = _make_grade(created_at=old_created_at)

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _scalar_one_or_none_mock(grade),  # tenant-scoped grade load
            ]
        )

        body = RegradeRequestCreate(dispute_text="Score seems too low.")

        with (
            patch("app.services.regrade_request.settings") as mock_settings,
            pytest.raises(RegradeWindowClosedError),
        ):
            mock_settings.regrade_window_days = 7
            mock_settings.regrade_max_per_grade = 1
            await create_regrade_request(db, grade.id, teacher_id, body)

    @pytest.mark.asyncio
    async def test_limit_reached_raises_limit_error(self) -> None:
        """Raises RegradeRequestLimitReachedError when the per-grade limit is already met."""
        teacher_id = _make_uuid()
        grade = _make_grade(created_at=datetime.now(UTC))

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _scalar_one_or_none_mock(grade),  # tenant-scoped grade load
                _scalar_one_mock(1),               # count = 1 = max_per_grade
            ]
        )

        body = RegradeRequestCreate(dispute_text="Score seems too low.")

        with (
            patch("app.services.regrade_request.settings") as mock_settings,
            pytest.raises(RegradeRequestLimitReachedError),
        ):
            mock_settings.regrade_window_days = 7
            mock_settings.regrade_max_per_grade = 1
            await create_regrade_request(db, grade.id, teacher_id, body)

    @pytest.mark.asyncio
    async def test_cross_teacher_raises_forbidden(self) -> None:
        """Raises ForbiddenError when grade belongs to a different teacher."""
        teacher_id = _make_uuid()
        grade_id = _make_uuid()

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _scalar_one_or_none_mock(None),      # tenant-scoped: not found
                _scalar_one_or_none_mock(grade_id),  # existence check: exists
            ]
        )

        body = RegradeRequestCreate(dispute_text="Score seems too low.")

        with pytest.raises(ForbiddenError):
            await create_regrade_request(db, grade_id, teacher_id, body)

    @pytest.mark.asyncio
    async def test_grade_not_found_raises_not_found(self) -> None:
        """Raises NotFoundError when grade does not exist at all."""
        teacher_id = _make_uuid()
        grade_id = _make_uuid()

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _scalar_one_or_none_mock(None),  # tenant-scoped: not found
                _scalar_one_or_none_mock(None),  # existence check: not found
            ]
        )

        body = RegradeRequestCreate(dispute_text="Score seems too low.")

        with pytest.raises(NotFoundError):
            await create_regrade_request(db, grade_id, teacher_id, body)

    @pytest.mark.asyncio
    async def test_invalid_criterion_score_id_raises_not_found(self) -> None:
        """Raises NotFoundError when criterion_score_id doesn't belong to the grade."""
        teacher_id = _make_uuid()
        grade = _make_grade(created_at=datetime.now(UTC))
        criterion_score_id = _make_uuid()

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _scalar_one_or_none_mock(grade),         # tenant-scoped grade
                _scalar_one_mock(0),                      # count = 0
                _scalar_one_or_none_mock(None),           # CS ownership: not found
            ]
        )

        body = RegradeRequestCreate(
            dispute_text="Score seems too low.",
            criterion_score_id=criterion_score_id,
        )

        with (
            patch("app.services.regrade_request.settings") as mock_settings,
            pytest.raises(NotFoundError),
        ):
            mock_settings.regrade_window_days = 7
            mock_settings.regrade_max_per_grade = 2
            await create_regrade_request(db, grade.id, teacher_id, body)


# ---------------------------------------------------------------------------
# Tests — list_regrade_requests_for_assignment
# ---------------------------------------------------------------------------


class TestListRegradeRequestsForAssignment:
    """Tests for list_regrade_requests_for_assignment service function."""

    @pytest.mark.asyncio
    async def test_happy_path_returns_list(self) -> None:
        """Returns a list of responses for all requests in the assignment."""
        teacher_id = _make_uuid()
        assignment_id = _make_uuid()
        assignment_mock = MagicMock()
        assignment_mock.id = assignment_id
        rr1 = _make_regrade_request(teacher_id=teacher_id)
        rr2 = _make_regrade_request(teacher_id=teacher_id)

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _scalar_one_or_none_mock(assignment_mock),  # tenant-scoped assignment
                _scalars_mock([rr1, rr2]),                  # list query
            ]
        )

        result = await list_regrade_requests_for_assignment(db, assignment_id, teacher_id)

        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_empty_assignment_returns_empty_list(self) -> None:
        """Returns an empty list when no regrade requests exist for the assignment."""
        teacher_id = _make_uuid()
        assignment_id = _make_uuid()
        assignment_mock = MagicMock()
        assignment_mock.id = assignment_id

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _scalar_one_or_none_mock(assignment_mock),  # tenant-scoped assignment
                _scalars_mock([]),                           # empty list
            ]
        )

        result = await list_regrade_requests_for_assignment(db, assignment_id, teacher_id)

        assert result == []

    @pytest.mark.asyncio
    async def test_cross_teacher_raises_forbidden(self) -> None:
        """Raises ForbiddenError when assignment belongs to a different teacher."""
        teacher_id = _make_uuid()
        assignment_id = _make_uuid()

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _scalar_one_or_none_mock(None),         # tenant-scoped: not found
                _scalar_one_or_none_mock(assignment_id), # existence check: exists
            ]
        )

        with pytest.raises(ForbiddenError):
            await list_regrade_requests_for_assignment(db, assignment_id, teacher_id)


# ---------------------------------------------------------------------------
# Tests — resolve_regrade_request
# ---------------------------------------------------------------------------


class TestResolveRegradeRequest:
    """Tests for resolve_regrade_request service function."""

    @pytest.mark.asyncio
    async def test_approve_happy_path_writes_audit_log(self) -> None:
        """Approving a request updates status and writes a regrade_resolved audit entry."""
        teacher_id = _make_uuid()
        request_id = _make_uuid()
        rr = _make_regrade_request(
            request_id=request_id,
            teacher_id=teacher_id,
            status=RegradeRequestStatus.open,
        )

        db = AsyncMock()
        db.add = MagicMock()
        db.execute = AsyncMock(
            side_effect=[
                _scalar_one_or_none_mock(rr),  # tenant-scoped request load
                # no new_criterion_score, so no CS/grade queries
            ]
        )
        db.refresh = AsyncMock(side_effect=lambda obj: None)

        body = RegradeRequestResolveRequest(resolution="approved", resolution_note="Well argued.")

        await resolve_regrade_request(db, request_id, teacher_id, body)

        assert rr.status == RegradeRequestStatus.approved
        assert rr.resolution_note == "Well argued."
        db.add.assert_called_once()  # audit log inserted
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_deny_happy_path_requires_and_stores_note(self) -> None:
        """Denying a request with a note succeeds and updates status to denied."""
        teacher_id = _make_uuid()
        request_id = _make_uuid()
        rr = _make_regrade_request(
            request_id=request_id,
            teacher_id=teacher_id,
            status=RegradeRequestStatus.open,
        )

        db = AsyncMock()
        db.add = MagicMock()
        db.execute = AsyncMock(
            side_effect=[
                _scalar_one_or_none_mock(rr),
            ]
        )
        db.refresh = AsyncMock(side_effect=lambda obj: None)

        body = RegradeRequestResolveRequest(
            resolution="denied",
            resolution_note="The original score is consistent with the rubric.",
        )

        await resolve_regrade_request(db, request_id, teacher_id, body)

        assert rr.status == RegradeRequestStatus.denied
        assert rr.resolution_note == "The original score is consistent with the rubric."

    @pytest.mark.asyncio
    async def test_deny_without_note_raises_validation_error(self) -> None:
        """Raises ValidationError when deny is requested without a resolution_note."""
        teacher_id = _make_uuid()
        request_id = _make_uuid()
        rr = _make_regrade_request(
            request_id=request_id,
            teacher_id=teacher_id,
            status=RegradeRequestStatus.open,
        )

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _scalar_one_or_none_mock(rr),
            ]
        )

        body = RegradeRequestResolveRequest(resolution="denied", resolution_note=None)

        with pytest.raises(ValidationError) as exc_info:
            await resolve_regrade_request(db, request_id, teacher_id, body)

        assert exc_info.value.field == "resolution_note"

    @pytest.mark.asyncio
    async def test_approve_with_new_criterion_score_updates_grade(self) -> None:
        """Approving a criterion-level request with new_criterion_score updates the criterion."""
        teacher_id = _make_uuid()
        request_id = _make_uuid()
        grade_id = _make_uuid()
        cs_id = _make_uuid()

        rr = _make_regrade_request(
            request_id=request_id,
            teacher_id=teacher_id,
            grade_id=grade_id,
            status=RegradeRequestStatus.open,
            criterion_score_id=cs_id,
        )
        cs = _make_criterion_score(grade_id=grade_id, cs_id=cs_id)
        grade_mock = MagicMock()
        grade_mock.id = grade_id
        grade_mock.total_score = Decimal("3")
        grade_mock.is_locked = False
        grade_mock.essay_version_id = _make_uuid()

        # assignment_mock.rubric_snapshot will be a MagicMock whose .get() returns
        # a MagicMock that iterates as [] — no criterion_data found, so bounds
        # validation is skipped (equivalent to no snapshot restriction in this test).
        assignment_mock = MagicMock()

        db = AsyncMock()
        db.add = MagicMock()
        db.execute = AsyncMock(
            side_effect=[
                _scalar_one_or_none_mock(rr),            # 1: tenant-scoped request
                _scalar_one_or_none_mock(cs),            # 2: load criterion score
                _scalar_one_or_none_mock(grade_mock),    # 3: load grade (is_locked check)
                _scalar_one_or_none_mock(assignment_mock),  # 4: load assignment (rubric_snapshot)
                _scalars_mock([4, 3]),                   # 5: final_scores for recompute
            ]
        )
        db.refresh = AsyncMock(side_effect=lambda obj: None)

        body = RegradeRequestResolveRequest(
            resolution="approved",
            resolution_note="After review, score is increased.",
            new_criterion_score=4,
        )

        await resolve_regrade_request(db, request_id, teacher_id, body)

        assert cs.teacher_score == 4
        assert cs.final_score == 4
        assert rr.status == RegradeRequestStatus.approved
        # Verify both audit log entries were inserted: score_override + regrade_resolved.
        assert db.add.call_count == 2
        added_entries = [call.args[0] for call in db.add.call_args_list]
        actions = {e.action for e in added_entries}
        assert "score_override" in actions
        assert "regrade_resolved" in actions
        # The regrade_resolved entry must be scoped to the grade (not the request).
        regrade_audit = next(e for e in added_entries if e.action == "regrade_resolved")
        assert regrade_audit.entity_type == "grade"
        assert regrade_audit.entity_id == grade_id

    @pytest.mark.asyncio
    async def test_cross_teacher_raises_forbidden(self) -> None:
        """Raises ForbiddenError when request belongs to a different teacher."""
        teacher_id = _make_uuid()
        request_id = _make_uuid()

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _scalar_one_or_none_mock(None),       # tenant-scoped: not found
                _scalar_one_or_none_mock(request_id), # existence check: exists
            ]
        )

        body = RegradeRequestResolveRequest(resolution="approved")

        with pytest.raises(ForbiddenError):
            await resolve_regrade_request(db, request_id, teacher_id, body)

    @pytest.mark.asyncio
    async def test_request_not_found_raises_not_found(self) -> None:
        """Raises NotFoundError when request does not exist at all."""
        teacher_id = _make_uuid()
        request_id = _make_uuid()

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _scalar_one_or_none_mock(None),  # tenant-scoped: not found
                _scalar_one_or_none_mock(None),  # existence check: not found
            ]
        )

        body = RegradeRequestResolveRequest(resolution="approved")

        with pytest.raises(NotFoundError):
            await resolve_regrade_request(db, request_id, teacher_id, body)

    @pytest.mark.asyncio
    async def test_new_criterion_score_without_criterion_raises_validation_error(self) -> None:
        """Raises ValidationError when new_criterion_score is set but request has no criterion."""
        teacher_id = _make_uuid()
        request_id = _make_uuid()
        rr = _make_regrade_request(
            request_id=request_id,
            teacher_id=teacher_id,
            status=RegradeRequestStatus.open,
            criterion_score_id=None,  # targets whole grade, not a criterion
        )

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _scalar_one_or_none_mock(rr),
            ]
        )

        body = RegradeRequestResolveRequest(
            resolution="approved",
            new_criterion_score=5,
        )

        with pytest.raises(ValidationError) as exc_info:
            await resolve_regrade_request(db, request_id, teacher_id, body)

        assert exc_info.value.field == "new_criterion_score"

    @pytest.mark.asyncio
    async def test_already_resolved_raises_conflict(self) -> None:
        """Raises ConflictError when the request is not in open status."""
        teacher_id = _make_uuid()
        request_id = _make_uuid()
        rr = _make_regrade_request(
            request_id=request_id,
            teacher_id=teacher_id,
            status=RegradeRequestStatus.approved,  # already resolved
        )

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _scalar_one_or_none_mock(rr),
            ]
        )

        body = RegradeRequestResolveRequest(resolution="approved")

        with pytest.raises(ConflictError):
            await resolve_regrade_request(db, request_id, teacher_id, body)

    @pytest.mark.asyncio
    async def test_criterion_score_not_found_during_resolution_raises_not_found(self) -> None:
        """Raises NotFoundError when criterion_score_id is set but the row is gone (FK NULL cascade)."""
        teacher_id = _make_uuid()
        request_id = _make_uuid()
        grade_id = _make_uuid()
        cs_id = _make_uuid()
        rr = _make_regrade_request(
            request_id=request_id,
            teacher_id=teacher_id,
            grade_id=grade_id,
            status=RegradeRequestStatus.open,
            criterion_score_id=cs_id,
        )

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _scalar_one_or_none_mock(rr),   # tenant-scoped request
                _scalar_one_or_none_mock(None),  # criterion score not found
            ]
        )

        body = RegradeRequestResolveRequest(
            resolution="approved",
            resolution_note="Score should be higher.",
            new_criterion_score=5,
        )

        with pytest.raises(NotFoundError):
            await resolve_regrade_request(db, request_id, teacher_id, body)

    @pytest.mark.asyncio
    async def test_grade_locked_raises_grade_locked_error(self) -> None:
        """Raises GradeLockedError when new_criterion_score targets a locked grade."""
        teacher_id = _make_uuid()
        request_id = _make_uuid()
        grade_id = _make_uuid()
        cs_id = _make_uuid()
        rr = _make_regrade_request(
            request_id=request_id,
            teacher_id=teacher_id,
            grade_id=grade_id,
            status=RegradeRequestStatus.open,
            criterion_score_id=cs_id,
        )
        cs = _make_criterion_score(grade_id=grade_id, cs_id=cs_id)
        grade_mock = MagicMock()
        grade_mock.id = grade_id
        grade_mock.is_locked = True  # grade is locked

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _scalar_one_or_none_mock(rr),         # tenant-scoped request
                _scalar_one_or_none_mock(cs),          # criterion score found
                _scalar_one_or_none_mock(grade_mock),  # grade is locked
            ]
        )

        body = RegradeRequestResolveRequest(
            resolution="approved",
            resolution_note="Score should be higher.",
            new_criterion_score=5,
        )

        with pytest.raises(GradeLockedError):
            await resolve_regrade_request(db, request_id, teacher_id, body)

    @pytest.mark.asyncio
    async def test_new_criterion_score_out_of_range_raises_validation_error(self) -> None:
        """Raises ValidationError when new_criterion_score falls outside rubric snapshot bounds."""
        teacher_id = _make_uuid()
        request_id = _make_uuid()
        grade_id = _make_uuid()
        cs_id = _make_uuid()
        rubric_criterion_id = _make_uuid()

        rr = _make_regrade_request(
            request_id=request_id,
            teacher_id=teacher_id,
            grade_id=grade_id,
            status=RegradeRequestStatus.open,
            criterion_score_id=cs_id,
        )
        cs = _make_criterion_score(grade_id=grade_id, cs_id=cs_id)
        cs.rubric_criterion_id = rubric_criterion_id

        grade_mock = MagicMock()
        grade_mock.id = grade_id
        grade_mock.is_locked = False
        grade_mock.essay_version_id = _make_uuid()

        # Build an assignment mock with a rubric_snapshot containing criterion bounds.
        assignment_mock = MagicMock()
        assignment_mock.rubric_snapshot = {
            "criteria": [
                {
                    "id": str(rubric_criterion_id),
                    "min_score": 0,
                    "max_score": 5,
                }
            ]
        }

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _scalar_one_or_none_mock(rr),              # 1: tenant-scoped request
                _scalar_one_or_none_mock(cs),              # 2: load criterion score
                _scalar_one_or_none_mock(grade_mock),      # 3: load grade (is_locked check)
                _scalar_one_or_none_mock(assignment_mock), # 4: load assignment (rubric_snapshot)
            ]
        )

        body = RegradeRequestResolveRequest(
            resolution="approved",
            resolution_note="Score should be higher.",
            new_criterion_score=10,  # out of [0, 5] range
        )

        with pytest.raises(ValidationError) as exc_info:
            await resolve_regrade_request(db, request_id, teacher_id, body)

        assert exc_info.value.field == "new_criterion_score"
