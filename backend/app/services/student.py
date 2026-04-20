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

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import ConflictError, ForbiddenError, NotFoundError, ValidationError
from app.models.class_ import Class
from app.models.class_enrollment import ClassEnrollment
from app.models.student import Student

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _get_class_owned_by(
    db: AsyncSession,
    class_id: uuid.UUID,
    teacher_id: uuid.UUID,
) -> Class:
    """Fetch a class row, raising NotFoundError or ForbiddenError.

    Returns 404 if the class does not exist; 403 if it belongs to another
    teacher.
    """
    ownership = await db.execute(select(Class.id, Class.teacher_id).where(Class.id == class_id))
    row = ownership.one_or_none()
    if row is None:
        raise NotFoundError("Class not found.")
    if row.teacher_id != teacher_id:
        raise ForbiddenError("You do not have access to this class.")

    result = await db.execute(
        select(Class).where(Class.id == class_id, Class.teacher_id == teacher_id)
    )
    class_obj = result.scalar_one_or_none()
    if class_obj is None:
        raise NotFoundError("Class not found.")
    return class_obj


async def _get_student_owned_by(
    db: AsyncSession,
    student_id: uuid.UUID,
    teacher_id: uuid.UUID,
) -> Student:
    """Fetch a student row, raising NotFoundError or ForbiddenError.

    Returns 404 if the student does not exist; 403 if it belongs to another
    teacher.
    """
    ownership = await db.execute(
        select(Student.id, Student.teacher_id).where(Student.id == student_id)
    )
    row = ownership.one_or_none()
    if row is None:
        raise NotFoundError("Student not found.")
    if row.teacher_id != teacher_id:
        raise ForbiddenError("You do not have access to this student.")

    result = await db.execute(
        select(Student).where(Student.id == student_id, Student.teacher_id == teacher_id)
    )
    student_obj = result.scalar_one_or_none()
    if student_obj is None:
        raise NotFoundError("Student not found.")
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
    await _get_class_owned_by(db, class_id, teacher_id)

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
    await _get_class_owned_by(db, class_id, teacher_id)

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
    await _get_class_owned_by(db, class_id, teacher_id)
    await _get_student_owned_by(db, student_id, teacher_id)

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
) -> Student:
    """Partially update a student's name and/or external ID.

    Only fields that are explicitly provided are updated.  Pass
    ``clear_external_id=True`` to explicitly set ``external_id`` to ``None``.

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

    await db.commit()
    await db.refresh(student)

    logger.info(
        "Student updated",
        extra={"student_id": str(student_id), "teacher_id": str(teacher_id)},
    )
    return student
