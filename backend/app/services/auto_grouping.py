"""Auto-grouping service (M6-01).

Business logic for computing and persisting skill-gap student groups within a
class.  Groups are generated from :class:`~app.models.student_skill_profile.StudentSkillProfile`
records and stored in :class:`~app.models.student_group.StudentGroup`.

Public API:
  - ``compute_and_persist_groups`` — load skill profiles for all enrolled
    students in a class, cluster by shared underperforming dimensions, enforce
    a minimum group size, and atomically replace the class's groups.

Grouping algorithm:
  1. Load all currently enrolled (non-removed) students for the class.
  2. Load their ``StudentSkillProfile`` records (students with no profile are
     skipped — they have no data to group on).
  3. For each student, identify "underperforming" skill dimensions where
     ``avg_score < underperformance_threshold``.
  4. Invert the mapping: for each skill dimension, collect the student_ids of
     all students who are underperforming in that dimension.
  5. Discard skill dimensions whose student_count is below ``min_group_size``.
  6. Within a single transaction, DELETE all existing ``StudentGroup`` rows for
     the (teacher_id, class_id) pair, then INSERT the freshly-computed groups.
     This DELETE → INSERT pattern is fully idempotent: re-running the task with
     the same inputs produces the same database state.

Tenant isolation:
  - ``teacher_id`` is passed explicitly to every query.
  - Class ownership is verified in every query via a WHERE clause on teacher_id.
  - The RLS tenant context (``app.current_teacher_id``) is set by the Celery
    task before opening the database session; see ``app.tasks.auto_grouping``.
  - No student PII (names, essay content, raw scores) is written to log
    statements — only entity IDs.

Security:
  - No student names or PII in any log statement.
  - ``student_ids`` in StudentGroup stores UUID strings, not names.
"""

from __future__ import annotations

import logging
import uuid
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import ConflictError, ForbiddenError, NotFoundError
from app.models.class_ import Class
from app.models.class_enrollment import ClassEnrollment
from app.models.student_group import StudentGroup
from app.models.student_skill_profile import StudentSkillProfile

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _assert_class_owned_by(
    db: AsyncSession,
    class_id: uuid.UUID,
    teacher_id: uuid.UUID,
) -> None:
    """Verify that the class exists and belongs to the given teacher.

    Raises:
        NotFoundError:  Class does not exist.
        ForbiddenError: Class exists but belongs to a different teacher.
    """
    result = await db.execute(select(Class.id, Class.teacher_id).where(Class.id == class_id))
    row = result.one_or_none()
    if row is None:
        raise NotFoundError("Class not found.")
    if row.teacher_id != teacher_id:
        raise ForbiddenError("You do not have access to this class.")


async def _load_enrolled_student_ids(
    db: AsyncSession,
    class_id: uuid.UUID,
    teacher_id: uuid.UUID,
) -> list[uuid.UUID]:
    """Return the IDs of all currently active enrollments for *class_id*.

    Filters out soft-removed students (``removed_at IS NOT NULL``).  Includes
    the ``teacher_id`` join so this query is fully tenant-scoped.
    """
    result = await db.execute(
        select(ClassEnrollment.student_id)
        .join(Class, ClassEnrollment.class_id == Class.id)
        .where(
            ClassEnrollment.class_id == class_id,
            Class.teacher_id == teacher_id,
            ClassEnrollment.removed_at.is_(None),
        )
    )
    return [row.student_id for row in result.all()]


async def _load_skill_profiles(
    db: AsyncSession,
    teacher_id: uuid.UUID,
    student_ids: list[uuid.UUID],
) -> list[StudentSkillProfile]:
    """Fetch StudentSkillProfile rows for the given students, tenant-scoped."""
    if not student_ids:
        return []

    result = await db.execute(
        select(StudentSkillProfile).where(
            StudentSkillProfile.teacher_id == teacher_id,
            StudentSkillProfile.student_id.in_(student_ids),
        )
    )
    return list(result.scalars().all())


def _build_groups(
    profiles: list[StudentSkillProfile],
    underperformance_threshold: float,
    min_group_size: int,
) -> list[dict[str, Any]]:
    """Cluster students by shared underperforming skill dimensions.

    Algorithm
    ---------
    For each profile, iterate the ``skill_scores`` dict.  Any skill whose
    ``avg_score`` is strictly below *underperformance_threshold* is considered
    underperforming for that student.  Invert the mapping to build a dict from
    skill_key → list[student_id_str].  Filter out skills where the student
    count is below *min_group_size*.

    Returns a list of group dicts with keys:
      ``skill_key``, ``label``, ``student_ids``, ``student_count``,
      ``computed_at``.
    """
    # skill_key → list of student UUID strings
    skill_students: dict[str, list[str]] = defaultdict(list)

    for profile in profiles:
        skill_scores: dict[str, Any] = profile.skill_scores or {}
        for skill_key, entry in skill_scores.items():
            if not isinstance(entry, dict):
                continue
            avg_score = entry.get("avg_score")
            if not isinstance(avg_score, (int, float)):
                continue
            if float(avg_score) < underperformance_threshold:
                skill_students[skill_key].append(str(profile.student_id))

    now_iso = datetime.now(UTC).isoformat()

    groups: list[dict[str, Any]] = []
    for skill_key, student_id_strs in sorted(skill_students.items()):
        if len(student_id_strs) < min_group_size:
            continue
        label = skill_key.replace("_", " ").title()
        groups.append(
            {
                "skill_key": skill_key,
                "label": label,
                "student_ids": sorted(student_id_strs),
                "student_count": len(student_id_strs),
                "computed_at": now_iso,
            }
        )

    return groups


# ---------------------------------------------------------------------------
# Public service function
# ---------------------------------------------------------------------------


async def compute_and_persist_groups(
    db: AsyncSession,
    teacher_id: uuid.UUID,
    class_id: uuid.UUID,
    *,
    underperformance_threshold: float,
    min_group_size: int,
) -> list[StudentGroup]:
    """Compute skill-gap groups for a class and atomically replace persisted groups.

    Loads all enrolled students' skill profiles for *class_id*, clusters them by
    shared underperforming skill dimensions, enforces *min_group_size*, and
    replaces the class's ``StudentGroup`` rows within a single transaction.

    Concurrency safety: a ``SELECT … FOR UPDATE`` on the ``Class`` row
    serialises concurrent invocations for the same ``class_id``.  Without this
    lock, two simultaneous tasks would each DELETE all existing groups and then
    both INSERT the same set of rows, causing the second transaction to hit the
    unique constraint on ``(teacher_id, class_id, skill_key)``.  If that race
    still occurs (e.g. during a retry after lock acquisition fails), the commit
    raises :exc:`~app.exceptions.ConflictError` so the task can retry safely.

    Args:
        db:                         Async database session.
        teacher_id:                 UUID of the owning teacher (tenant isolation).
        class_id:                   UUID of the class to group.
        underperformance_threshold: Skill avg_score below this float is "weak".
        min_group_size:             Groups smaller than this are discarded.

    Returns:
        The newly persisted :class:`StudentGroup` records (empty list if none
        met the minimum size threshold).

    Raises:
        NotFoundError:  Class does not exist.
        ForbiddenError: Class belongs to a different teacher.
        ConflictError:  Concurrent task conflict — caller should retry.
    """
    await _assert_class_owned_by(db, class_id, teacher_id)

    student_ids = await _load_enrolled_student_ids(db, class_id, teacher_id)

    profiles = await _load_skill_profiles(db, teacher_id, student_ids)

    groups = _build_groups(profiles, underperformance_threshold, min_group_size)

    # ------------------------------------------------------------------
    # Acquire a row-level lock on the Class to serialise concurrent task
    # executions for the same class.  Without this, two tasks racing on
    # the same (teacher_id, class_id) can both DELETE all existing rows
    # and then both INSERT identical rows, causing the second transaction
    # to hit the unique constraint on (teacher_id, class_id, skill_key).
    # The lock is released automatically when the transaction commits.
    # ------------------------------------------------------------------
    await db.execute(
        select(Class.id).where(
            Class.id == class_id,
            Class.teacher_id == teacher_id,
        ).with_for_update()
    )

    await db.execute(
        delete(StudentGroup).where(
            StudentGroup.teacher_id == teacher_id,
            StudentGroup.class_id == class_id,
        )
    )

    persisted: list[StudentGroup] = []
    for group in groups:
        # Standard SQLAlchemy insert (not pg_insert / ON CONFLICT) is sufficient
        # here because the FOR UPDATE lock above guarantees the DELETE cleared all
        # prior rows before we reach this point, eliminating the need for upsert.
        stmt = (
            insert(StudentGroup)
            .values(
                id=uuid.uuid4(),
                teacher_id=teacher_id,
                class_id=class_id,
                skill_key=group["skill_key"],
                label=group["label"],
                student_ids=group["student_ids"],
                student_count=group["student_count"],
                computed_at=datetime.now(UTC),
            )
            .returning(StudentGroup)
        )
        result = await db.execute(stmt)
        row = result.scalar_one()
        persisted.append(row)

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        # Two concurrent tasks for the same class can both DELETE and then
        # both INSERT the same (teacher_id, class_id, skill_key) rows.  The
        # FOR UPDATE lock above serialises the common case, but this guard
        # catches any residual races (e.g., a retry that overlaps a first run).
        raise ConflictError(
            "Unique constraint conflict — concurrent task already inserted these groups."
        ) from None

    logger.info(
        "Auto-grouping complete",
        extra={
            "teacher_id": str(teacher_id),
            "class_id": str(class_id),
            "group_count": len(persisted),
        },
    )

    return persisted
