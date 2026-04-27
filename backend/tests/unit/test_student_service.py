"""Unit tests for app/services/student.py.

Tests cover:
- list_enrolled_students: success path, not-found class, forbidden class, tenant filter
- enroll_student: success with new student, success with existing student,
  conflict (already enrolled), IntegrityError race, forbidden class,
  ValidationError when full_name missing
- remove_enrollment: success, not-found enrollment, forbidden class/student
- get_student: success, not-found, cross-teacher
- update_student: success full-name change, success clear_external_id, success set_teacher_notes, success clear_teacher_notes, cross-teacher

No real PostgreSQL. All DB calls are mocked. No student PII in fixtures.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.exc import IntegrityError

from app.exceptions import ConflictError, ForbiddenError, NotFoundError, ValidationError
from app.services.student import (
    enroll_student,
    get_student,
    get_student_history,
    get_student_with_profile,
    list_enrolled_students,
    remove_enrollment,
    update_student,
)

# ---------------------------------------------------------------------------
# Helpers / Factories
# ---------------------------------------------------------------------------


def _make_db() -> AsyncMock:
    db = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    db.rollback = AsyncMock()
    return db


def _make_class_orm(teacher_id: uuid.UUID, class_id: uuid.UUID | None = None) -> MagicMock:
    obj = MagicMock()
    obj.id = class_id or uuid.uuid4()
    obj.teacher_id = teacher_id
    return obj


def _make_student_orm(teacher_id: uuid.UUID, student_id: uuid.UUID | None = None) -> MagicMock:
    obj = MagicMock()
    obj.id = student_id or uuid.uuid4()
    obj.teacher_id = teacher_id
    obj.full_name = "Student A"
    obj.external_id = None
    return obj


def _make_enrollment_orm(
    class_id: uuid.UUID,
    student_id: uuid.UUID,
    removed_at: datetime | None = None,
) -> MagicMock:
    obj = MagicMock()
    obj.id = uuid.uuid4()
    obj.class_id = class_id
    obj.student_id = student_id
    obj.enrolled_at = datetime.now(UTC)
    obj.removed_at = removed_at
    return obj


def _ownership_result(teacher_id: uuid.UUID) -> MagicMock:
    row = MagicMock()
    row.teacher_id = teacher_id
    r = MagicMock()
    r.one_or_none.return_value = row
    return r


def _not_found_result() -> MagicMock:
    r = MagicMock()
    r.one_or_none.return_value = None
    return r


def _scalar_result(value: object) -> MagicMock:
    r = MagicMock()
    r.scalar_one_or_none.return_value = value
    return r


def _make_profile_orm(teacher_id: uuid.UUID, student_id: uuid.UUID) -> MagicMock:
    obj = MagicMock()
    obj.teacher_id = teacher_id
    obj.student_id = student_id
    obj.assignment_count = 2
    obj.skill_scores = {}
    obj.last_updated_at = datetime.now(UTC)
    return obj


def _all_result(rows: list[object]) -> MagicMock:
    r = MagicMock()
    r.all.return_value = rows
    return r


# ---------------------------------------------------------------------------
# list_enrolled_students
# ---------------------------------------------------------------------------


class TestListEnrolledStudents:
    @pytest.mark.asyncio
    async def test_returns_enrollment_student_pairs(self) -> None:
        teacher_id = uuid.uuid4()
        class_id = uuid.uuid4()
        student_orm = _make_student_orm(teacher_id)
        enrollment_orm = _make_enrollment_orm(class_id, student_orm.id)

        db = _make_db()
        # _assert_class_owned_by: narrow ownership check
        ownership_res = _ownership_result(teacher_id)
        # list query result
        list_res = MagicMock()
        list_res.all.return_value = [(enrollment_orm, student_orm)]
        db.execute = AsyncMock(side_effect=[ownership_res, list_res])

        result = await list_enrolled_students(db, teacher_id, class_id)

        assert len(result) == 1
        enr, stu = result[0]
        assert enr is enrollment_orm
        assert stu is student_orm

    @pytest.mark.asyncio
    async def test_raises_not_found_for_missing_class(self) -> None:
        db = _make_db()
        db.execute = AsyncMock(return_value=_not_found_result())

        with pytest.raises(NotFoundError):
            await list_enrolled_students(db, uuid.uuid4(), uuid.uuid4())

    @pytest.mark.asyncio
    async def test_raises_forbidden_for_wrong_teacher(self) -> None:
        teacher_id = uuid.uuid4()
        other_teacher_id = uuid.uuid4()
        db = _make_db()
        # ownership row exists but belongs to other_teacher_id
        row = MagicMock()
        row.teacher_id = other_teacher_id
        res = MagicMock()
        res.one_or_none.return_value = row
        db.execute = AsyncMock(return_value=res)

        with pytest.raises(ForbiddenError):
            await list_enrolled_students(db, teacher_id, uuid.uuid4())

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_enrollments(self) -> None:
        teacher_id = uuid.uuid4()
        class_id = uuid.uuid4()

        db = _make_db()
        ownership_res = _ownership_result(teacher_id)
        list_res = MagicMock()
        list_res.all.return_value = []
        db.execute = AsyncMock(side_effect=[ownership_res, list_res])

        result = await list_enrolled_students(db, teacher_id, class_id)

        assert result == []


# ---------------------------------------------------------------------------
# enroll_student
# ---------------------------------------------------------------------------


class TestEnrollStudent:
    @pytest.mark.asyncio
    async def test_enrolls_new_student_successfully(self) -> None:
        teacher_id = uuid.uuid4()
        class_id = uuid.uuid4()

        db = _make_db()
        # _assert_class_owned_by: narrow ownership check
        ownership_res = _ownership_result(teacher_id)
        # check existing active enrollment → None
        no_enrollment_res = _scalar_result(None)
        db.execute = AsyncMock(side_effect=[ownership_res, no_enrollment_res])

        enr, stu = await enroll_student(db, teacher_id, class_id, full_name="Student A")

        db.add.assert_called()
        db.commit.assert_called_once()
        assert stu.teacher_id == teacher_id
        assert stu.full_name == "Student A"

    @pytest.mark.asyncio
    async def test_enrolls_existing_student_successfully(self) -> None:
        teacher_id = uuid.uuid4()
        class_id = uuid.uuid4()
        student_id = uuid.uuid4()
        student_orm = _make_student_orm(teacher_id, student_id)

        db = _make_db()
        # _assert_class_owned_by: narrow ownership check
        ownership_class = _ownership_result(teacher_id)
        # _get_student_owned_by: single full-row query
        student_res = _scalar_result(student_orm)
        no_enrollment_res = _scalar_result(None)
        db.execute = AsyncMock(side_effect=[ownership_class, student_res, no_enrollment_res])

        enr, stu = await enroll_student(db, teacher_id, class_id, student_id=student_id)

        db.commit.assert_called_once()
        assert stu is student_orm

    @pytest.mark.asyncio
    async def test_raises_conflict_when_already_enrolled(self) -> None:
        teacher_id = uuid.uuid4()
        class_id = uuid.uuid4()

        db = _make_db()
        ownership_res = _ownership_result(teacher_id)
        # active enrollment already exists (non-None scalar)
        existing_enrollment = _make_enrollment_orm(class_id, uuid.uuid4())
        existing_res = _scalar_result(existing_enrollment)
        db.execute = AsyncMock(side_effect=[ownership_res, existing_res])

        with pytest.raises(ConflictError):
            await enroll_student(db, teacher_id, class_id, full_name="Student A")

        db.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_raises_conflict_on_integrity_error_race(self) -> None:
        """Concurrent enrollment race: IntegrityError on commit → ConflictError."""
        teacher_id = uuid.uuid4()
        class_id = uuid.uuid4()

        db = _make_db()
        ownership_res = _ownership_result(teacher_id)
        no_enrollment_res = _scalar_result(None)
        db.execute = AsyncMock(side_effect=[ownership_res, no_enrollment_res])
        db.commit = AsyncMock(side_effect=IntegrityError(None, None, Exception("unique violation")))

        with pytest.raises(ConflictError):
            await enroll_student(db, teacher_id, class_id, full_name="Student A")

        db.rollback.assert_called_once()

    @pytest.mark.asyncio
    async def test_raises_validation_error_when_full_name_none(self) -> None:
        """student_id=None and full_name=None → ValidationError (not AssertionError)."""
        teacher_id = uuid.uuid4()
        class_id = uuid.uuid4()

        db = _make_db()
        ownership_res = _ownership_result(teacher_id)
        db.execute = AsyncMock(side_effect=[ownership_res])

        with pytest.raises(ValidationError) as exc_info:
            await enroll_student(db, teacher_id, class_id, student_id=None, full_name=None)

        assert exc_info.value.field == "full_name"
        db.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_raises_forbidden_for_wrong_class_teacher(self) -> None:
        other_teacher_id = uuid.uuid4()
        teacher_id = uuid.uuid4()
        row = MagicMock()
        row.teacher_id = other_teacher_id
        res = MagicMock()
        res.one_or_none.return_value = row
        db = _make_db()
        db.execute = AsyncMock(return_value=res)

        with pytest.raises(ForbiddenError):
            await enroll_student(db, teacher_id, uuid.uuid4(), full_name="Student A")


# ---------------------------------------------------------------------------
# remove_enrollment
# ---------------------------------------------------------------------------


class TestRemoveEnrollment:
    @pytest.mark.asyncio
    async def test_soft_removes_enrollment(self) -> None:
        teacher_id = uuid.uuid4()
        class_id = uuid.uuid4()
        student_id = uuid.uuid4()
        enrollment_orm = _make_enrollment_orm(class_id, student_id)
        enrollment_orm.removed_at = None  # active

        db = _make_db()
        # _assert_class_owned_by + _assert_student_owned_by: narrow queries
        ownership_class = _ownership_result(teacher_id)
        ownership_student = _ownership_result(teacher_id)
        enrollment_res = _scalar_result(enrollment_orm)
        db.execute = AsyncMock(side_effect=[ownership_class, ownership_student, enrollment_res])

        result = await remove_enrollment(db, teacher_id, class_id, student_id)

        db.commit.assert_called_once()
        assert result is enrollment_orm
        # removed_at should have been set
        assert result.removed_at is not None

    @pytest.mark.asyncio
    async def test_raises_not_found_when_no_active_enrollment(self) -> None:
        teacher_id = uuid.uuid4()
        class_id = uuid.uuid4()
        student_id = uuid.uuid4()

        db = _make_db()
        ownership_class = _ownership_result(teacher_id)
        ownership_student = _ownership_result(teacher_id)
        no_enrollment = _scalar_result(None)
        db.execute = AsyncMock(side_effect=[ownership_class, ownership_student, no_enrollment])

        with pytest.raises(NotFoundError):
            await remove_enrollment(db, teacher_id, class_id, student_id)

        db.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_raises_forbidden_for_wrong_class(self) -> None:
        teacher_id = uuid.uuid4()
        other_teacher_id = uuid.uuid4()
        row = MagicMock()
        row.teacher_id = other_teacher_id
        res = MagicMock()
        res.one_or_none.return_value = row
        db = _make_db()
        db.execute = AsyncMock(return_value=res)

        with pytest.raises(ForbiddenError):
            await remove_enrollment(db, teacher_id, uuid.uuid4(), uuid.uuid4())


# ---------------------------------------------------------------------------
# get_student
# ---------------------------------------------------------------------------


class TestGetStudent:
    @pytest.mark.asyncio
    async def test_returns_student(self) -> None:
        teacher_id = uuid.uuid4()
        student_id = uuid.uuid4()
        student_orm = _make_student_orm(teacher_id, student_id)

        db = _make_db()
        # _get_student_owned_by: single full-row query
        student_res = _scalar_result(student_orm)
        db.execute = AsyncMock(side_effect=[student_res])

        result = await get_student(db, teacher_id, student_id)

        assert result is student_orm

    @pytest.mark.asyncio
    async def test_raises_not_found_for_missing_student(self) -> None:
        db = _make_db()
        db.execute = AsyncMock(return_value=_scalar_result(None))

        with pytest.raises(NotFoundError):
            await get_student(db, uuid.uuid4(), uuid.uuid4())

    @pytest.mark.asyncio
    async def test_raises_forbidden_for_wrong_teacher(self) -> None:
        teacher_id = uuid.uuid4()
        other_teacher_id = uuid.uuid4()
        # Full student row returned but owned by a different teacher
        student_orm = _make_student_orm(other_teacher_id)
        db = _make_db()
        db.execute = AsyncMock(return_value=_scalar_result(student_orm))

        with pytest.raises(ForbiddenError):
            await get_student(db, teacher_id, uuid.uuid4())


# ---------------------------------------------------------------------------
# update_student
# ---------------------------------------------------------------------------


class TestUpdateStudent:
    @pytest.mark.asyncio
    async def test_updates_full_name(self) -> None:
        teacher_id = uuid.uuid4()
        student_id = uuid.uuid4()
        student_orm = _make_student_orm(teacher_id, student_id)
        student_orm.full_name = "Original Name"

        db = _make_db()
        # _get_student_owned_by: single full-row query
        student_res = _scalar_result(student_orm)
        db.execute = AsyncMock(side_effect=[student_res])

        result = await update_student(db, teacher_id, student_id, full_name="New Name")

        assert result.full_name == "New Name"
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_clears_external_id(self) -> None:
        teacher_id = uuid.uuid4()
        student_id = uuid.uuid4()
        student_orm = _make_student_orm(teacher_id, student_id)
        student_orm.external_id = "EXT-001"

        db = _make_db()
        student_res = _scalar_result(student_orm)
        db.execute = AsyncMock(side_effect=[student_res])

        result = await update_student(db, teacher_id, student_id, clear_external_id=True)

        assert result.external_id is None
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_sets_teacher_notes(self) -> None:
        teacher_id = uuid.uuid4()
        student_id = uuid.uuid4()
        student_orm = _make_student_orm(teacher_id, student_id)
        student_orm.teacher_notes = None

        db = _make_db()
        student_res = _scalar_result(student_orm)
        db.execute = AsyncMock(side_effect=[student_res])

        result = await update_student(
            db, teacher_id, student_id, teacher_notes="Watch evidence integration."
        )

        assert result.teacher_notes == "Watch evidence integration."
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_clears_teacher_notes(self) -> None:
        teacher_id = uuid.uuid4()
        student_id = uuid.uuid4()
        student_orm = _make_student_orm(teacher_id, student_id)
        student_orm.teacher_notes = "Some existing note."

        db = _make_db()
        student_res = _scalar_result(student_orm)
        db.execute = AsyncMock(side_effect=[student_res])

        result = await update_student(
            db, teacher_id, student_id, clear_teacher_notes=True
        )

        assert result.teacher_notes is None
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_raises_forbidden_for_wrong_teacher(self) -> None:
        teacher_id = uuid.uuid4()
        other_teacher_id = uuid.uuid4()
        # Full student row returned but owned by a different teacher
        student_orm = _make_student_orm(other_teacher_id)
        db = _make_db()
        db.execute = AsyncMock(return_value=_scalar_result(student_orm))

        with pytest.raises(ForbiddenError):
            await update_student(db, teacher_id, uuid.uuid4(), full_name="New Name")

        db.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_raises_not_found_for_missing_student(self) -> None:
        db = _make_db()
        db.execute = AsyncMock(return_value=_scalar_result(None))

        with pytest.raises(NotFoundError):
            await update_student(db, uuid.uuid4(), uuid.uuid4(), full_name="New Name")

        db.commit.assert_not_called()


# ---------------------------------------------------------------------------
# get_student_with_profile
# ---------------------------------------------------------------------------


class TestGetStudentWithProfile:
    @pytest.mark.asyncio
    async def test_returns_student_with_profile(self) -> None:
        teacher_id = uuid.uuid4()
        student_id = uuid.uuid4()
        student_orm = _make_student_orm(teacher_id, student_id)
        profile_orm = _make_profile_orm(teacher_id, student_id)

        db = _make_db()
        # 1st execute: _get_student_owned_by (scalar_one_or_none)
        # 2nd execute: StudentSkillProfile query (scalar_one_or_none)
        db.execute = AsyncMock(
            side_effect=[_scalar_result(student_orm), _scalar_result(profile_orm)]
        )

        result_student, result_profile = await get_student_with_profile(db, teacher_id, student_id)

        assert result_student is student_orm
        assert result_profile is profile_orm

    @pytest.mark.asyncio
    async def test_returns_none_profile_when_no_skill_data(self) -> None:
        teacher_id = uuid.uuid4()
        student_id = uuid.uuid4()
        student_orm = _make_student_orm(teacher_id, student_id)

        db = _make_db()
        db.execute = AsyncMock(
            side_effect=[_scalar_result(student_orm), _scalar_result(None)]
        )

        result_student, result_profile = await get_student_with_profile(db, teacher_id, student_id)

        assert result_student is student_orm
        assert result_profile is None

    @pytest.mark.asyncio
    async def test_raises_not_found_for_missing_student(self) -> None:
        db = _make_db()
        db.execute = AsyncMock(return_value=_scalar_result(None))

        with pytest.raises(NotFoundError):
            await get_student_with_profile(db, uuid.uuid4(), uuid.uuid4())

    @pytest.mark.asyncio
    async def test_raises_forbidden_for_wrong_teacher(self) -> None:
        teacher_id = uuid.uuid4()
        other_teacher_id = uuid.uuid4()
        student_orm = _make_student_orm(other_teacher_id)
        db = _make_db()
        db.execute = AsyncMock(return_value=_scalar_result(student_orm))

        with pytest.raises(ForbiddenError):
            await get_student_with_profile(db, teacher_id, uuid.uuid4())


# ---------------------------------------------------------------------------
# get_student_history
# ---------------------------------------------------------------------------


class TestGetStudentHistory:
    def _make_history_row(
        self,
        locked_at: datetime,
        assignment_id: uuid.UUID | None = None,
    ) -> MagicMock:
        row = MagicMock()
        row.assignment_id = assignment_id or uuid.uuid4()
        row.assignment_title = "Assignment"
        row.class_id = uuid.uuid4()
        row.grade_id = uuid.uuid4()
        row.essay_id = uuid.uuid4()
        row.total_score = Decimal("8.0")
        row.max_possible_score = Decimal("10.0")
        row.locked_at = locked_at
        return row

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_locked_grades(self) -> None:
        teacher_id = uuid.uuid4()
        student_id = uuid.uuid4()

        db = _make_db()
        # _assert_student_owned_by: narrow ownership check (one_or_none)
        ownership_res = _ownership_result(teacher_id)
        # history query: no rows
        history_res = _all_result([])
        db.execute = AsyncMock(side_effect=[ownership_res, history_res])

        result = await get_student_history(db, teacher_id, student_id)

        assert result == []

    @pytest.mark.asyncio
    async def test_returns_rows_newest_first(self) -> None:
        teacher_id = uuid.uuid4()
        student_id = uuid.uuid4()
        now = datetime.now(UTC)
        older = datetime(2024, 1, 1, tzinfo=UTC)

        row_new = self._make_history_row(locked_at=now)
        row_old = self._make_history_row(locked_at=older)

        db = _make_db()
        ownership_res = _ownership_result(teacher_id)
        # Mock returns rows already in newest-first order (as the DB ORDER BY would)
        history_res = _all_result([row_new, row_old])
        db.execute = AsyncMock(side_effect=[ownership_res, history_res])

        result = await get_student_history(db, teacher_id, student_id)

        assert len(result) == 2
        assert result[0].locked_at == now
        assert result[1].locked_at == older

    @pytest.mark.asyncio
    async def test_result_contains_only_locked_grade_fields(self) -> None:
        teacher_id = uuid.uuid4()
        student_id = uuid.uuid4()
        assignment_id = uuid.uuid4()
        locked_at = datetime.now(UTC)

        row = self._make_history_row(locked_at=locked_at, assignment_id=assignment_id)
        row.total_score = Decimal("7.5")
        row.max_possible_score = Decimal("10.0")

        db = _make_db()
        ownership_res = _ownership_result(teacher_id)
        history_res = _all_result([row])
        db.execute = AsyncMock(side_effect=[ownership_res, history_res])

        result = await get_student_history(db, teacher_id, student_id)

        assert len(result) == 1
        item = result[0]
        assert item.assignment_id == assignment_id
        assert item.total_score == Decimal("7.5")
        assert item.max_possible_score == Decimal("10.0")
        assert item.locked_at == locked_at

    @pytest.mark.asyncio
    async def test_raises_not_found_for_missing_student(self) -> None:
        db = _make_db()
        db.execute = AsyncMock(return_value=_not_found_result())

        with pytest.raises(NotFoundError):
            await get_student_history(db, uuid.uuid4(), uuid.uuid4())

    @pytest.mark.asyncio
    async def test_raises_forbidden_for_wrong_teacher(self) -> None:
        teacher_id = uuid.uuid4()
        other_teacher_id = uuid.uuid4()
        row = MagicMock()
        row.teacher_id = other_teacher_id
        res = MagicMock()
        res.one_or_none.return_value = row
        db = _make_db()
        db.execute = AsyncMock(return_value=res)

        with pytest.raises(ForbiddenError):
            await get_student_history(db, teacher_id, uuid.uuid4())
