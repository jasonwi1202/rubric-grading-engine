"""StudentSkillProfile service.

Business logic for reading and upserting the per-student skill-score
aggregation introduced in M5-02.

Public API:
  - ``get_skill_profile``    — fetch the profile for a student (tenant-scoped).
  - ``upsert_skill_profile`` — insert or update the profile for a student,
                               scoped to a specific teacher.

Tenant isolation:
  Every function accepts ``teacher_id`` and includes it in the upsert /
  ownership check.  The unique constraint on (teacher_id, student_id)
  guarantees that concurrent upserts for the same teacher+student converge to
  a single row and never mix data across tenants.

No student PII (names, essay content, raw scores) is written to log
statements.  Only entity IDs are logged.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import ForbiddenError, NotFoundError
from app.models.student import Student
from app.models.student_skill_profile import StudentSkillProfile

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _assert_student_owned_by(
    db: AsyncSession,
    student_id: uuid.UUID,
    teacher_id: uuid.UUID,
) -> None:
    """Verify that the student exists and belongs to the given teacher.

    Raises :exc:`NotFoundError` if the student does not exist.
    Raises :exc:`ForbiddenError` if the student belongs to a different teacher.
    """
    result = await db.execute(
        select(Student.id, Student.teacher_id).where(Student.id == student_id)
    )
    row = result.one_or_none()
    if row is None:
        raise NotFoundError("Student not found.")
    if row.teacher_id != teacher_id:
        raise ForbiddenError("You do not have access to this student.")


# ---------------------------------------------------------------------------
# Public service functions
# ---------------------------------------------------------------------------


async def get_skill_profile(
    db: AsyncSession,
    teacher_id: uuid.UUID,
    student_id: uuid.UUID,
) -> StudentSkillProfile:
    """Fetch the skill profile for a student (tenant-scoped).

    Both the student ownership and the profile row are filtered by
    ``teacher_id`` so a teacher can never retrieve another teacher's profile.

    Raises:
        NotFoundError: If the student or their profile does not exist.
        ForbiddenError: If the student belongs to a different teacher.
    """
    await _assert_student_owned_by(db, student_id, teacher_id)

    result = await db.execute(
        select(StudentSkillProfile).where(
            StudentSkillProfile.teacher_id == teacher_id,
            StudentSkillProfile.student_id == student_id,
        )
    )
    profile = result.scalar_one_or_none()
    if profile is None:
        raise NotFoundError("Skill profile not found for this student.")
    return profile


async def upsert_skill_profile(
    db: AsyncSession,
    teacher_id: uuid.UUID,
    student_id: uuid.UUID,
    *,
    skill_scores: dict[str, Any],
    assignment_count: int,
) -> StudentSkillProfile:
    """Insert or update the skill profile for a teacher+student pair.

    Uses PostgreSQL ``INSERT … ON CONFLICT DO UPDATE`` so concurrent
    callers safely converge to the latest values without raising an
    :exc:`IntegrityError`.

    The ``last_updated_at`` timestamp is always refreshed to the current UTC
    time on every upsert, regardless of whether any score actually changed.

    Args:
        db:               Async SQLAlchemy session (must not be in an open
                          transaction that the caller wants to preserve —
                          this function commits).
        teacher_id:       Teacher who owns the student record.
        student_id:       Student whose profile is being updated.
        skill_scores:     Mapping of canonical skill names to score metadata.
                          Shape: {skill_name: {avg_score, trend, data_points,
                          last_updated}}.
        assignment_count: Total number of graded assignments contributing to
                          the profile.

    Returns:
        The (freshly loaded) ``StudentSkillProfile`` row after the upsert.

    Raises:
        NotFoundError:  If the student does not exist.
        ForbiddenError: If the student belongs to a different teacher.
    """
    await _assert_student_owned_by(db, student_id, teacher_id)

    now = datetime.now(UTC)
    profile_id = uuid.uuid4()

    stmt = (
        pg_insert(StudentSkillProfile)
        .values(
            id=profile_id,
            teacher_id=teacher_id,
            student_id=student_id,
            skill_scores=skill_scores,
            assignment_count=assignment_count,
            last_updated_at=now,
        )
        .on_conflict_do_update(
            constraint="uq_skill_profile_teacher_student",
            set_={
                "skill_scores": skill_scores,
                "assignment_count": assignment_count,
                "last_updated_at": now,
            },
        )
        .returning(StudentSkillProfile.id)
    )

    result = await db.execute(stmt)
    returned_id: uuid.UUID = result.scalar_one()
    await db.commit()

    # Reload the full row so the caller gets an up-to-date ORM object.
    profile_result = await db.execute(
        select(StudentSkillProfile).where(StudentSkillProfile.id == returned_id)
    )
    profile = profile_result.scalar_one()

    logger.info(
        "Student skill profile upserted",
        extra={
            "student_id": str(student_id),
            "teacher_id": str(teacher_id),
            "assignment_count": assignment_count,
        },
    )
    return profile
