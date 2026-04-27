"""Student service.

Business logic for student CRUD and class-enrollment management:

- ``list_enrolled_students``  — list active enrollments for a class.
- ``enroll_student``          — enroll an existing or new student in a class.
- ``remove_enrollment``       — soft-remove a student from a class (sets removed_at).
- ``get_student``             — fetch a single student (tenant-scoped).
- ``update_student``          — update student name / external ID.

No student PII (name, external_id) is written to log statements.  Only
entity IDs are logged.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import NamedTuple

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import ConflictError, ForbiddenError, NotFoundError, ValidationError
from app.models.assignment import Assignment
from app.models.class_ import Class
from app.models.class_enrollment import ClassEnrollment
from app.models.essay import Essay, EssayVersion
from app.models.grade import Grade
from app.models.student import Student
from app.models.student_skill_profile import StudentSkillProfile

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Named-tuple for student history rows
# ---------------------------------------------------------------------------


class StudentHistoryRow(NamedTuple):
    """Typed row returned by :func:`get_student_history`."""

    assignment_id: uuid.UUID
    assignment_title: str
    class_id: uuid.UUID
    grade_id: uuid.UUID
    essay_id: uuid.UUID
    total_score: Decimal
    max_possible_score: Decimal
    locked_at: datetime


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _assert_class_owned_by(
    db: AsyncSession,
    class_id: uuid.UUID,
    teacher_id: uuid.UUID,
) -> None:
    """Check class existence and ownership without loading the full Class row.

    Raises :exc:`NotFoundError` if the class does not exist; raises
    :exc:`ForbiddenError` if it belongs to a different teacher.  Uses a single
    narrow query (id + teacher_id only) — callers that discard the Class ORM
    object should prefer this over a full load.
    """
    result = await db.execute(select(Class.id, Class.teacher_id).where(Class.id == class_id))
    row = result.one_or_none()
    if row is None:
        raise NotFoundError("Class not found.")
    if row.teacher_id != teacher_id:
        raise ForbiddenError("You do not have access to this class.")


async def _assert_student_owned_by(
    db: AsyncSession,
    student_id: uuid.UUID,
    teacher_id: uuid.UUID,
) -> None:
    """Check student existence and ownership without loading the full Student row.

    Raises :exc:`NotFoundError` if the student does not exist; raises
    :exc:`ForbiddenError` if it belongs to a different teacher.  Uses a single
    narrow query (id + teacher_id only) — callers that discard the Student ORM
    object should prefer this over a full load.
    """
    result = await db.execute(
        select(Student.id, Student.teacher_id).where(Student.id == student_id)
    )
    row = result.one_or_none()
    if row is None:
        raise NotFoundError("Student not found.")
    if row.teacher_id != teacher_id:
        raise ForbiddenError("You do not have access to this student.")


async def _get_student_owned_by(
    db: AsyncSession,
    student_id: uuid.UUID,
    teacher_id: uuid.UUID,
) -> Student:
    """Fetch the full Student row after verifying ownership.

    Raises :exc:`NotFoundError` if the student does not exist; raises
    :exc:`ForbiddenError` if it belongs to a different teacher.  Uses a single
    query that loads the full row and validates ownership in Python.

    Note: ``teacher_id`` is intentionally *not* in the WHERE clause so that
    we can distinguish a missing student (404) from a cross-tenant access
    attempt (403).  Adding ``Student.teacher_id == teacher_id`` to the query
    would fold both cases into a ``None`` result, making it impossible to
    return the required 403 for cross-tenant requests.
    """
    result = await db.execute(select(Student).where(Student.id == student_id))
    student_obj = result.scalar_one_or_none()
    if student_obj is None:
        raise NotFoundError("Student not found.")
    if student_obj.teacher_id != teacher_id:
        raise ForbiddenError("You do not have access to this student.")
    return student_obj


# ---------------------------------------------------------------------------
# Public service functions
# ---------------------------------------------------------------------------


async def list_enrolled_students(
    db: AsyncSession,
    teacher_id: uuid.UUID,
    class_id: uuid.UUID,
) -> list[tuple[ClassEnrollment, Student]]:
    """Return all active (non-removed) enrollments for a class.

    Each item is a ``(ClassEnrollment, Student)`` pair ordered by student
    full_name ascending.

    Raises:
        NotFoundError: If the class does not exist.
        ForbiddenError: If the class belongs to a different teacher.
    """
    await _assert_class_owned_by(db, class_id, teacher_id)

    result = await db.execute(
        select(ClassEnrollment, Student)
        .join(Student, ClassEnrollment.student_id == Student.id)
        .where(
            ClassEnrollment.class_id == class_id,
            ClassEnrollment.removed_at.is_(None),
            Student.teacher_id == teacher_id,
        )
        .order_by(Student.full_name)
    )
    return [(row[0], row[1]) for row in result.all()]


async def enroll_student(
    db: AsyncSession,
    teacher_id: uuid.UUID,
    class_id: uuid.UUID,
    *,
    student_id: uuid.UUID | None = None,
    full_name: str | None = None,
    external_id: str | None = None,
) -> tuple[ClassEnrollment, Student]:
    """Enrol a student in a class.

    If ``student_id`` is provided, the existing student is enrolled (they must
    be owned by ``teacher_id``).  Otherwise a new Student is created using
    ``full_name`` (and optionally ``external_id``).

    Raises:
        NotFoundError: Class or student not found.
        ForbiddenError: Class/student belongs to a different teacher.
        ConflictError: Student is already actively enrolled in the class.
    """
    # Validate class ownership.
    await _assert_class_owned_by(db, class_id, teacher_id)

    if student_id is not None:
        student = await _get_student_owned_by(db, student_id, teacher_id)
    else:
        # Create a new student record.
        if full_name is None:
            raise ValidationError(
                "full_name is required when student_id is not provided.", field="full_name"
            )
        student = Student(
            teacher_id=teacher_id,
            full_name=full_name,
            external_id=external_id,
        )
        db.add(student)
        await db.flush()  # assign student.id without committing yet

    # Check for an existing active enrollment.
    existing = await db.execute(
        select(ClassEnrollment).where(
            ClassEnrollment.class_id == class_id,
            ClassEnrollment.student_id == student.id,
            ClassEnrollment.removed_at.is_(None),
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise ConflictError("Student is already enrolled in this class.")

    enrollment = ClassEnrollment(
        class_id=class_id,
        student_id=student.id,
    )
    db.add(enrollment)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise ConflictError("Student is already enrolled in this class.") from None
    await db.refresh(enrollment)
    await db.refresh(student)

    logger.info(
        "Student enrolled",
        extra={
            "class_id": str(class_id),
            "student_id": str(student.id),
            "teacher_id": str(teacher_id),
        },
    )
    return enrollment, student


async def remove_enrollment(
    db: AsyncSession,
    teacher_id: uuid.UUID,
    class_id: uuid.UUID,
    student_id: uuid.UUID,
) -> ClassEnrollment:
    """Soft-remove a student from a class by setting ``removed_at``.

    The student record and all associated history are preserved.

    Raises:
        NotFoundError: Class not found, student not found, or no active
            enrollment for this student in this class.
        ForbiddenError: Class or student belongs to a different teacher.
    """
    await _assert_class_owned_by(db, class_id, teacher_id)
    await _assert_student_owned_by(db, student_id, teacher_id)

    result = await db.execute(
        select(ClassEnrollment).where(
            ClassEnrollment.class_id == class_id,
            ClassEnrollment.student_id == student_id,
            ClassEnrollment.removed_at.is_(None),
        )
    )
    enrollment = result.scalar_one_or_none()
    if enrollment is None:
        raise NotFoundError("Active enrollment not found.")

    enrollment.removed_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(enrollment)

    logger.info(
        "Student removed from class",
        extra={
            "class_id": str(class_id),
            "student_id": str(student_id),
            "teacher_id": str(teacher_id),
        },
    )
    return enrollment


async def get_student(
    db: AsyncSession,
    teacher_id: uuid.UUID,
    student_id: uuid.UUID,
) -> Student:
    """Fetch a single student (tenant-scoped).

    Raises:
        NotFoundError: If the student does not exist.
        ForbiddenError: If the student belongs to a different teacher.
    """
    return await _get_student_owned_by(db, student_id, teacher_id)


async def update_student(
    db: AsyncSession,
    teacher_id: uuid.UUID,
    student_id: uuid.UUID,
    *,
    full_name: str | None = None,
    external_id: str | None = None,
    clear_external_id: bool = False,
    teacher_notes: str | None = None,
    clear_teacher_notes: bool = False,
) -> Student:
    """Partially update a student's name, external ID, and/or teacher notes.

    Only fields that are explicitly provided are updated.  Pass
    ``clear_external_id=True`` to explicitly set ``external_id`` to ``None``.
    Pass ``clear_teacher_notes=True`` to explicitly set ``teacher_notes`` to ``None``.

    When both ``teacher_notes`` and ``clear_teacher_notes`` are provided,
    ``clear_teacher_notes`` takes precedence and the field is set to ``None``.

    Raises:
        NotFoundError: If the student does not exist.
        ForbiddenError: If the student belongs to a different teacher.
    """
    student = await _get_student_owned_by(db, student_id, teacher_id)

    if full_name is not None:
        student.full_name = full_name
    if clear_external_id:
        student.external_id = None
    elif external_id is not None:
        student.external_id = external_id
    if clear_teacher_notes:
        student.teacher_notes = None
    elif teacher_notes is not None:
        student.teacher_notes = teacher_notes

    await db.commit()
    await db.refresh(student)

    logger.info(
        "Student updated",
        extra={"student_id": str(student_id), "teacher_id": str(teacher_id)},
    )
    return student


async def get_student_with_profile(
    db: AsyncSession,
    teacher_id: uuid.UUID,
    student_id: uuid.UUID,
) -> tuple[Student, StudentSkillProfile | None]:
    """Fetch a student together with their optional skill profile (tenant-scoped).

    Raises:
        NotFoundError: If the student does not exist.
        ForbiddenError: If the student belongs to a different teacher.
    """
    student = await _get_student_owned_by(db, student_id, teacher_id)

    profile_result = await db.execute(
        select(StudentSkillProfile).where(
            StudentSkillProfile.teacher_id == teacher_id,
            StudentSkillProfile.student_id == student_id,
        )
    )
    profile = profile_result.scalar_one_or_none()
    return student, profile


async def get_student_history(
    db: AsyncSession,
    teacher_id: uuid.UUID,
    student_id: uuid.UUID,
) -> list[StudentHistoryRow]:
    """Return all locked graded assignments for a student, newest-first.

    Each row exposes: assignment_id, assignment_title, class_id, grade_id,
    essay_id, total_score, max_possible_score, locked_at.

    Raises:
        NotFoundError: If the student does not exist.
        ForbiddenError: If the student belongs to a different teacher.
    """
    await _assert_student_owned_by(db, student_id, teacher_id)

    result = await db.execute(
        select(
            Assignment.id.label("assignment_id"),
            Assignment.title.label("assignment_title"),
            Assignment.class_id.label("class_id"),
            Grade.id.label("grade_id"),
            Essay.id.label("essay_id"),
            Grade.total_score,
            Grade.max_possible_score,
            Grade.locked_at,
        )
        .join(EssayVersion, Grade.essay_version_id == EssayVersion.id)
        .join(Essay, EssayVersion.essay_id == Essay.id)
        .join(Assignment, Essay.assignment_id == Assignment.id)
        .join(Class, Assignment.class_id == Class.id)
        .where(
            Essay.student_id == student_id,
            Class.teacher_id == teacher_id,
            Grade.is_locked.is_(True),
            Grade.locked_at.is_not(None),
        )
        .order_by(Grade.locked_at.desc())
    )
    return [
        StudentHistoryRow(
            assignment_id=row.assignment_id,
            assignment_title=row.assignment_title,
            class_id=row.class_id,
            grade_id=row.grade_id,
            essay_id=row.essay_id,
            total_score=row.total_score,
            max_possible_score=row.max_possible_score,
            locked_at=row.locked_at,
        )
        for row in result.all()
    ]
