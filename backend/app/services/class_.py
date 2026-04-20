"""Class service.

Business logic for class CRUD operations:

- ``list_classes``  — list all classes for a teacher (with optional filters).
- ``create_class``  — create a new class for a teacher.
- ``get_class``     — fetch a single class (tenant-scoped).
- ``update_class``  — update class metadata.
- ``archive_class`` — soft-archive a class (sets is_archived=True).

No student PII is collected or processed here.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import ForbiddenError, NotFoundError
from app.models.class_ import Class

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

    Uses a two-step check: verify existence first (404), then ownership (403).
    This avoids leaking whether another teacher's class exists.
    """
    ownership_result = await db.execute(
        select(Class.id, Class.teacher_id).where(Class.id == class_id)
    )
    ownership_row = ownership_result.one_or_none()
    if ownership_row is None:
        raise NotFoundError("Class not found.")
    if ownership_row.teacher_id != teacher_id:
        raise ForbiddenError("You do not have access to this class.")

    class_result = await db.execute(
        select(Class).where(
            Class.id == class_id,
            Class.teacher_id == teacher_id,
        )
    )
    class_obj = class_result.scalar_one_or_none()
    if class_obj is None:
        raise NotFoundError("Class not found.")
    return class_obj


# ---------------------------------------------------------------------------
# Public service functions
# ---------------------------------------------------------------------------


async def list_classes(
    db: AsyncSession,
    teacher_id: uuid.UUID,
    academic_year: str | None = None,
    is_archived: bool | None = None,
) -> list[Class]:
    """List all classes for a teacher, optionally filtered.

    Results are ordered newest-first.
    """
    stmt = select(Class).where(Class.teacher_id == teacher_id).order_by(Class.created_at.desc())
    if academic_year is not None:
        stmt = stmt.where(Class.academic_year == academic_year)
    if is_archived is not None:
        stmt = stmt.where(Class.is_archived == is_archived)

    result = await db.execute(stmt)
    return list(result.scalars().all())


async def create_class(
    db: AsyncSession,
    teacher_id: uuid.UUID,
    name: str,
    subject: str,
    grade_level: str,
    academic_year: str,
) -> Class:
    """Create a new class owned by the teacher."""
    new_class = Class(
        teacher_id=teacher_id,
        name=name,
        subject=subject,
        grade_level=grade_level,
        academic_year=academic_year,
    )
    db.add(new_class)
    await db.commit()
    await db.refresh(new_class)

    logger.info(
        "Class created",
        extra={"class_id": str(new_class.id), "teacher_id": str(teacher_id)},
    )
    return new_class


async def get_class(
    db: AsyncSession,
    teacher_id: uuid.UUID,
    class_id: uuid.UUID,
) -> Class:
    """Fetch a single class (tenant-scoped).

    Raises:
        NotFoundError: If the class does not exist.
        ForbiddenError: If the class belongs to a different teacher.
    """
    return await _get_class_owned_by(db, class_id, teacher_id)


async def update_class(
    db: AsyncSession,
    teacher_id: uuid.UUID,
    class_id: uuid.UUID,
    name: str | None,
    subject: str | None,
    grade_level: str | None,
    academic_year: str | None,
) -> Class:
    """Partially update a class's metadata.

    Only fields that are not None are updated.

    Raises:
        NotFoundError: If the class does not exist.
        ForbiddenError: If the class belongs to a different teacher.
    """
    class_obj = await _get_class_owned_by(db, class_id, teacher_id)

    if name is not None:
        class_obj.name = name
    if subject is not None:
        class_obj.subject = subject
    if grade_level is not None:
        class_obj.grade_level = grade_level
    if academic_year is not None:
        class_obj.academic_year = academic_year

    await db.commit()
    await db.refresh(class_obj)

    logger.info(
        "Class updated",
        extra={"class_id": str(class_id), "teacher_id": str(teacher_id)},
    )
    return class_obj


async def archive_class(
    db: AsyncSession,
    teacher_id: uuid.UUID,
    class_id: uuid.UUID,
) -> Class:
    """Archive a class by setting ``is_archived=True``.

    This is a soft operation — the class record is not deleted.

    Raises:
        NotFoundError: If the class does not exist.
        ForbiddenError: If the class belongs to a different teacher.
    """
    class_obj = await _get_class_owned_by(db, class_id, teacher_id)
    class_obj.is_archived = True
    await db.commit()
    await db.refresh(class_obj)

    logger.info(
        "Class archived",
        extra={"class_id": str(class_id), "teacher_id": str(teacher_id)},
    )
    return class_obj
