"""Unit tests for app/services/grade.py.

All database calls are mocked — no real PostgreSQL.
No student PII in any fixture.

Coverage:
- get_grade_for_essay: happy path, essay not found, forbidden, grade not found.
- update_grade_feedback: happy path with audit log, locked grade rejects edit.
- override_criterion: happy path with audit log, locked grade rejects edit,
  neither field provided raises ValidationError, criterion not found.
- lock_grade: happy path with audit log, idempotent on already-locked grade.
- Cross-teacher access returns ForbiddenError (403).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.exceptions import ForbiddenError, GradeLockedError, NotFoundError, ValidationError
from app.models.grade import ConfidenceLevel, StrictnessLevel
from app.services.grade import (
    get_grade_for_essay,
    lock_grade,
    override_criterion,
    update_grade_feedback,
)

# ---------------------------------------------------------------------------
# Helpers / factories
# ---------------------------------------------------------------------------


def _make_uuid() -> uuid.UUID:
    return uuid.uuid4()


def _make_criterion_score(
    grade_id: uuid.UUID | None = None,
    criterion_score_id: uuid.UUID | None = None,
    ai_score: int = 3,
    teacher_score: int | None = None,
    teacher_feedback: str | None = None,
) -> MagicMock:
    cs = MagicMock()
    cs.id = criterion_score_id or _make_uuid()
    cs.grade_id = grade_id or _make_uuid()
    cs.rubric_criterion_id = _make_uuid()
    cs.ai_score = ai_score
    cs.teacher_score = teacher_score
    cs.final_score = teacher_score if teacher_score is not None else ai_score
    cs.ai_justification = "Justification text for testing purposes."
    cs.ai_feedback = "AI feedback text."
    cs.teacher_feedback = teacher_feedback
    cs.confidence = ConfidenceLevel.high
    cs.created_at = datetime.now(UTC)
    return cs


def _make_grade(
    grade_id: uuid.UUID | None = None,
    essay_version_id: uuid.UUID | None = None,
    is_locked: bool = False,
    summary_feedback_edited: str | None = None,
) -> MagicMock:
    g = MagicMock()
    g.id = grade_id or _make_uuid()
    g.essay_version_id = essay_version_id or _make_uuid()
    g.total_score = Decimal("3")
    g.max_possible_score = Decimal("5")
    g.summary_feedback = "AI-generated summary feedback."
    g.summary_feedback_edited = summary_feedback_edited
    g.strictness = StrictnessLevel.balanced
    g.ai_model = "gpt-4o"
    g.prompt_version = "grading-v1"
    g.is_locked = is_locked
    g.locked_at = None
    g.created_at = datetime.now(UTC)
    return g


def _make_essay_version(essay_id: uuid.UUID | None = None) -> MagicMock:
    ev = MagicMock()
    ev.id = _make_uuid()
    ev.essay_id = essay_id or _make_uuid()
    ev.version_number = 1
    return ev


def _make_essay(assignment_id: uuid.UUID | None = None) -> MagicMock:
    e = MagicMock()
    e.id = _make_uuid()
    e.assignment_id = assignment_id or _make_uuid()
    return e


# ---------------------------------------------------------------------------
# DB mock helpers
# ---------------------------------------------------------------------------


def _scalars_mock(items: list) -> MagicMock:
    """Return a mock whose .scalars().all() returns *items*."""
    result = MagicMock()
    scalars = MagicMock()
    scalars.all = MagicMock(return_value=items)
    result.scalars = MagicMock(return_value=scalars)
    return result


def _scalar_one_or_none_mock(value: object) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=value)
    return result


# ---------------------------------------------------------------------------
# Tests — get_grade_for_essay
# ---------------------------------------------------------------------------


class TestGetGradeForEssay:
    """Tests for get_grade_for_essay service function."""

    @pytest.mark.asyncio
    async def test_happy_path_returns_grade_response(self) -> None:
        """Returns a GradeResponse with criterion scores on success."""
        teacher_id = _make_uuid()
        essay = _make_essay()
        essay_version = _make_essay_version(essay.id)
        grade = _make_grade(essay_version_id=essay_version.id)
        criterion_score = _make_criterion_score(grade_id=grade.id)

        db = AsyncMock()
        db.add = MagicMock()
        db.execute = AsyncMock(
            side_effect=[
                # 1. Essay tenant-scoped query
                _scalar_one_or_none_mock(essay),
                # 2. Latest EssayVersion query
                _scalar_one_or_none_mock(essay_version),
                # 3. Grade query
                _scalar_one_or_none_mock(grade),
                # 4. CriterionScore list query
                _scalars_mock([criterion_score]),
            ]
        )

        response = await get_grade_for_essay(db, essay.id, teacher_id)

        assert response.id == grade.id
        assert len(response.criterion_scores) == 1
        assert response.criterion_scores[0].id == criterion_score.id

    @pytest.mark.asyncio
    async def test_essay_not_found_raises_not_found(self) -> None:
        """Raises NotFoundError when essay does not exist at all."""
        teacher_id = _make_uuid()
        essay_id = _make_uuid()

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _scalar_one_or_none_mock(None),  # tenant-scoped: not found
                _scalar_one_or_none_mock(None),  # existence check: not found
            ]
        )

        with pytest.raises(NotFoundError):
            await get_grade_for_essay(db, essay_id, teacher_id)

    @pytest.mark.asyncio
    async def test_cross_teacher_raises_forbidden(self) -> None:
        """Raises ForbiddenError when essay exists but belongs to another teacher."""
        teacher_id = _make_uuid()
        essay_id = _make_uuid()

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _scalar_one_or_none_mock(None),  # tenant-scoped: not found
                _scalar_one_or_none_mock(essay_id),  # existence check: exists
            ]
        )

        with pytest.raises(ForbiddenError):
            await get_grade_for_essay(db, essay_id, teacher_id)

    @pytest.mark.asyncio
    async def test_grade_not_found_raises_not_found(self) -> None:
        """Raises NotFoundError when essay exists but has no grade."""
        teacher_id = _make_uuid()
        essay = _make_essay()
        essay_version = _make_essay_version(essay.id)

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _scalar_one_or_none_mock(essay),  # essay found
                _scalar_one_or_none_mock(essay_version),  # version found
                _scalar_one_or_none_mock(None),  # grade not found
            ]
        )

        with pytest.raises(NotFoundError):
            await get_grade_for_essay(db, essay.id, teacher_id)


# ---------------------------------------------------------------------------
# Tests — update_grade_feedback
# ---------------------------------------------------------------------------


class TestUpdateGradeFeedback:
    """Tests for update_grade_feedback service function."""

    @pytest.mark.asyncio
    async def test_happy_path_updates_feedback_and_writes_audit_log(self) -> None:
        """Updates summary_feedback_edited and writes a feedback_edited audit entry."""
        teacher_id = _make_uuid()
        grade = _make_grade()
        criterion_score = _make_criterion_score(grade_id=grade.id)
        new_feedback = "Updated teacher feedback text."

        added_objects: list[object] = []

        db = AsyncMock()
        db.add = MagicMock(side_effect=lambda obj: added_objects.append(obj))
        db.execute = AsyncMock(
            side_effect=[
                # _load_grade_tenant_scoped: tenant-scoped grade query
                _scalar_one_or_none_mock(grade),
                # _load_criterion_scores
                _scalars_mock([criterion_score]),
            ]
        )

        response = await update_grade_feedback(db, grade.id, teacher_id, new_feedback)

        assert grade.summary_feedback_edited == new_feedback
        assert response.summary_feedback_edited == new_feedback
        assert db.commit.called

        from app.models.audit_log import AuditLog as AuditLogModel

        audit_entries = [o for o in added_objects if isinstance(o, AuditLogModel)]
        assert len(audit_entries) == 1, "Expected one feedback_edited audit entry"
        entry = audit_entries[0]
        assert entry.action == "feedback_edited"
        assert entry.entity_type == "grade"
        assert entry.entity_id == grade.id
        assert entry.teacher_id == teacher_id
        assert entry.before_value is not None
        assert entry.after_value is not None
        assert entry.after_value["summary_feedback"] == new_feedback

    @pytest.mark.asyncio
    async def test_before_value_uses_existing_edited_feedback_when_set(self) -> None:
        """before_value captures the current edited text, not the AI text."""
        teacher_id = _make_uuid()
        existing_edited = "Previously edited feedback."
        grade = _make_grade(summary_feedback_edited=existing_edited)
        criterion_score = _make_criterion_score(grade_id=grade.id)

        added_objects: list[object] = []
        db = AsyncMock()
        db.add = MagicMock(side_effect=lambda obj: added_objects.append(obj))
        db.execute = AsyncMock(
            side_effect=[
                _scalar_one_or_none_mock(grade),
                _scalars_mock([criterion_score]),
            ]
        )

        await update_grade_feedback(db, grade.id, teacher_id, "New feedback.")

        from app.models.audit_log import AuditLog as AuditLogModel

        audit_entries = [o for o in added_objects if isinstance(o, AuditLogModel)]
        assert len(audit_entries) == 1
        assert audit_entries[0].before_value["summary_feedback"] == existing_edited

    @pytest.mark.asyncio
    async def test_locked_grade_raises_grade_locked_error(self) -> None:
        """Raises GradeLockedError (409) when the grade is locked."""
        teacher_id = _make_uuid()
        grade = _make_grade(is_locked=True)

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _scalar_one_or_none_mock(grade),
            ]
        )

        with pytest.raises(GradeLockedError):
            await update_grade_feedback(db, grade.id, teacher_id, "New feedback.")

    @pytest.mark.asyncio
    async def test_cross_teacher_raises_forbidden(self) -> None:
        """Raises ForbiddenError when grade belongs to another teacher."""
        teacher_id = _make_uuid()
        grade_id = _make_uuid()

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _scalar_one_or_none_mock(None),  # tenant-scoped: not found
                _scalar_one_or_none_mock(grade_id),  # existence check: exists
            ]
        )

        with pytest.raises(ForbiddenError):
            await update_grade_feedback(db, grade_id, teacher_id, "New feedback.")

    @pytest.mark.asyncio
    async def test_grade_not_found_raises_not_found(self) -> None:
        """Raises NotFoundError when grade does not exist."""
        teacher_id = _make_uuid()
        grade_id = _make_uuid()

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _scalar_one_or_none_mock(None),  # tenant-scoped: not found
                _scalar_one_or_none_mock(None),  # existence check: not found
            ]
        )

        with pytest.raises(NotFoundError):
            await update_grade_feedback(db, grade_id, teacher_id, "New feedback.")


# ---------------------------------------------------------------------------
# Tests — override_criterion
# ---------------------------------------------------------------------------


class TestOverrideCriterion:
    """Tests for override_criterion service function."""

    @pytest.mark.asyncio
    async def test_happy_path_score_override_writes_audit_log(self) -> None:
        """Overrides teacher_score, updates final_score, writes score_override audit entry."""
        teacher_id = _make_uuid()
        grade = _make_grade()
        criterion_score = _make_criterion_score(grade_id=grade.id, ai_score=2)

        added_objects: list[object] = []
        db = AsyncMock()
        db.add = MagicMock(side_effect=lambda obj: added_objects.append(obj))
        db.execute = AsyncMock(
            side_effect=[
                _scalar_one_or_none_mock(grade),  # load grade tenant-scoped
                _scalar_one_or_none_mock(criterion_score),  # load criterion score
                _scalars_mock([criterion_score]),  # load all criterion scores
            ]
        )

        await override_criterion(
            db,
            grade.id,
            criterion_score.id,
            teacher_id,
            teacher_score=4,
            teacher_feedback=None,
        )

        assert criterion_score.teacher_score == 4
        assert criterion_score.final_score == 4
        assert db.commit.called

        from app.models.audit_log import AuditLog as AuditLogModel

        audit_entries = [o for o in added_objects if isinstance(o, AuditLogModel)]
        assert len(audit_entries) == 1
        entry = audit_entries[0]
        assert entry.action == "score_override"
        assert entry.entity_type == "criterion_score"
        assert entry.entity_id == criterion_score.id
        assert entry.teacher_id == teacher_id
        assert entry.before_value is not None
        assert entry.after_value is not None
        assert entry.after_value["teacher_score"] == 4
        assert entry.after_value["final_score"] == 4

    @pytest.mark.asyncio
    async def test_feedback_only_override_writes_audit_log(self) -> None:
        """Overrides teacher_feedback only (score unchanged) with audit entry."""
        teacher_id = _make_uuid()
        grade = _make_grade()
        criterion_score = _make_criterion_score(grade_id=grade.id)

        added_objects: list[object] = []
        db = AsyncMock()
        db.add = MagicMock(side_effect=lambda obj: added_objects.append(obj))
        db.execute = AsyncMock(
            side_effect=[
                _scalar_one_or_none_mock(grade),
                _scalar_one_or_none_mock(criterion_score),
                _scalars_mock([criterion_score]),
            ]
        )

        await override_criterion(
            db,
            grade.id,
            criterion_score.id,
            teacher_id,
            teacher_score=None,
            teacher_feedback="Great use of evidence.",
        )

        assert criterion_score.teacher_feedback == "Great use of evidence."

        from app.models.audit_log import AuditLog as AuditLogModel

        audit_entries = [o for o in added_objects if isinstance(o, AuditLogModel)]
        assert len(audit_entries) == 1
        assert audit_entries[0].action == "score_override"

    @pytest.mark.asyncio
    async def test_neither_field_provided_raises_validation_error(self) -> None:
        """Raises ValidationError when both teacher_score and teacher_feedback are None."""
        db = AsyncMock()

        with pytest.raises(ValidationError):
            await override_criterion(
                db,
                _make_uuid(),
                _make_uuid(),
                _make_uuid(),
                teacher_score=None,
                teacher_feedback=None,
            )

    @pytest.mark.asyncio
    async def test_locked_grade_raises_grade_locked_error(self) -> None:
        """Raises GradeLockedError when the grade is locked."""
        teacher_id = _make_uuid()
        grade = _make_grade(is_locked=True)

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[_scalar_one_or_none_mock(grade)])

        with pytest.raises(GradeLockedError):
            await override_criterion(
                db,
                grade.id,
                _make_uuid(),
                teacher_id,
                teacher_score=5,
                teacher_feedback=None,
            )

    @pytest.mark.asyncio
    async def test_criterion_not_in_grade_raises_not_found(self) -> None:
        """Raises NotFoundError when criterion score does not belong to this grade."""
        teacher_id = _make_uuid()
        grade = _make_grade()

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _scalar_one_or_none_mock(grade),  # grade found
                _scalar_one_or_none_mock(None),  # criterion score not found
            ]
        )

        with pytest.raises(NotFoundError):
            await override_criterion(
                db,
                grade.id,
                _make_uuid(),
                teacher_id,
                teacher_score=3,
                teacher_feedback=None,
            )

    @pytest.mark.asyncio
    async def test_cross_teacher_raises_forbidden(self) -> None:
        """Raises ForbiddenError when grade belongs to another teacher."""
        teacher_id = _make_uuid()
        grade_id = _make_uuid()

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _scalar_one_or_none_mock(None),  # tenant-scoped: not found
                _scalar_one_or_none_mock(grade_id),  # existence check: exists
            ]
        )

        with pytest.raises(ForbiddenError):
            await override_criterion(
                db,
                grade_id,
                _make_uuid(),
                teacher_id,
                teacher_score=3,
                teacher_feedback=None,
            )


# ---------------------------------------------------------------------------
# Tests — lock_grade
# ---------------------------------------------------------------------------


class TestLockGrade:
    """Tests for lock_grade service function."""

    @pytest.mark.asyncio
    async def test_happy_path_locks_grade_and_writes_audit_log(self) -> None:
        """Sets is_locked=True and locked_at, writes grade_locked audit entry."""
        teacher_id = _make_uuid()
        grade = _make_grade(is_locked=False)
        criterion_score = _make_criterion_score(grade_id=grade.id)

        added_objects: list[object] = []
        db = AsyncMock()
        db.add = MagicMock(side_effect=lambda obj: added_objects.append(obj))
        db.execute = AsyncMock(
            side_effect=[
                _scalar_one_or_none_mock(grade),
                _scalars_mock([criterion_score]),
            ]
        )

        response = await lock_grade(db, grade.id, teacher_id)

        assert grade.is_locked is True
        assert grade.locked_at is not None
        assert response.is_locked is True
        assert db.commit.called

        from app.models.audit_log import AuditLog as AuditLogModel

        audit_entries = [o for o in added_objects if isinstance(o, AuditLogModel)]
        assert len(audit_entries) == 1
        entry = audit_entries[0]
        assert entry.action == "grade_locked"
        assert entry.entity_type == "grade"
        assert entry.entity_id == grade.id
        assert entry.teacher_id == teacher_id
        assert entry.before_value == {"is_locked": False}
        assert entry.after_value == {"is_locked": True}

    @pytest.mark.asyncio
    async def test_already_locked_grade_is_idempotent(self) -> None:
        """Locking an already-locked grade succeeds without writing another audit entry."""
        teacher_id = _make_uuid()
        grade = _make_grade(is_locked=True)
        criterion_score = _make_criterion_score(grade_id=grade.id)

        added_objects: list[object] = []
        db = AsyncMock()
        db.add = MagicMock(side_effect=lambda obj: added_objects.append(obj))
        db.execute = AsyncMock(
            side_effect=[
                _scalar_one_or_none_mock(grade),
                _scalars_mock([criterion_score]),
            ]
        )

        response = await lock_grade(db, grade.id, teacher_id)

        assert response.is_locked is True
        # No additional commit or audit entry should be written.
        assert not db.commit.called

        from app.models.audit_log import AuditLog as AuditLogModel

        audit_entries = [o for o in added_objects if isinstance(o, AuditLogModel)]
        assert len(audit_entries) == 0, "No audit entry when grade already locked"

    @pytest.mark.asyncio
    async def test_cross_teacher_raises_forbidden(self) -> None:
        """Raises ForbiddenError when grade belongs to another teacher."""
        teacher_id = _make_uuid()
        grade_id = _make_uuid()

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _scalar_one_or_none_mock(None),  # tenant-scoped: not found
                _scalar_one_or_none_mock(grade_id),  # existence check: exists
            ]
        )

        with pytest.raises(ForbiddenError):
            await lock_grade(db, grade_id, teacher_id)

    @pytest.mark.asyncio
    async def test_grade_not_found_raises_not_found(self) -> None:
        """Raises NotFoundError when grade does not exist."""
        teacher_id = _make_uuid()
        grade_id = _make_uuid()

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _scalar_one_or_none_mock(None),  # tenant-scoped: not found
                _scalar_one_or_none_mock(None),  # existence check: not found
            ]
        )

        with pytest.raises(NotFoundError):
            await lock_grade(db, grade_id, teacher_id)
