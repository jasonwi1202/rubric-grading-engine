"""Auto-grouping service (M6-01 / M6-02).

Business logic for computing and persisting skill-gap student groups within a
class.  Groups are generated from :class:`~app.models.student_skill_profile.StudentSkillProfile`
records and stored in :class:`~app.models.student_group.StudentGroup`.

Public API:
  - ``compute_and_persist_groups`` — load skill profiles for all enrolled
    students in a class, cluster by shared underperforming dimensions, enforce
    a minimum group size, and atomically replace the class's groups.
  - ``list_class_groups`` — return all current groups for a class, with
    resolved student names and stability status, for the M6-02 API.

Grouping algorithm:
  1. Load all currently enrolled (non-removed) students for the class.
  2. Load their ``StudentSkillProfile`` records (students with no profile are
     skipped — they have no data to group on).
  3. For each student, identify "underperforming" skill dimensions where
     ``avg_score < underperformance_threshold``.
  4. Invert the mapping: for each skill dimension, collect the student_ids of
     all students who are underperforming in that dimension.
  5. Discard skill dimensions whose student_count is below ``min_group_size``.
  6. Load existing non-exited groups to determine stability:
     - skill_keys present in both old and new groups → 'persistent'
     - skill_keys only in new groups → 'new'
     - skill_keys only in old groups → 'exited' (stored with empty student list)
  7. Within a single transaction, DELETE all existing ``StudentGroup`` rows for
     the (teacher_id, class_id) pair, then INSERT the freshly-computed groups
     plus any exited groups.

Tenant isolation:
  - ``teacher_id`` is passed explicitly to every query.
  - Class ownership is verified in every query via a WHERE clause on teacher_id.
  - The RLS tenant context (``app.current_teacher_id``) is set by the Celery
    task on the opened database session before any tenant-scoped queries run;
    see ``app.tasks.auto_grouping``.
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
from app.models.student import Student
from app.models.student_group import StudentGroup
from app.models.student_skill_profile import StudentSkillProfile
from app.schemas.student_group import (
    ClassGroupsResponse,
    StudentGroupResponse,
    StudentInGroupResponse,
)

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


async def _load_existing_active_skill_keys(
    db: AsyncSession,
    teacher_id: uuid.UUID,
    class_id: uuid.UUID,
) -> set[str]:
    """Return the set of skill_keys for non-exited groups for *class_id*.

    Used to determine group stability on the next computation run.
    Groups with ``stability='exited'`` are excluded — they have already
    transitioned out and should not be treated as 'persistent'.
    """
    result = await db.execute(
        select(StudentGroup.skill_key).where(
            StudentGroup.teacher_id == teacher_id,
            StudentGroup.class_id == class_id,
            StudentGroup.stability != "exited",
        )
    )
    return {row.skill_key for row in result.all()}


def _build_groups(
    profiles: list[StudentSkillProfile],
    underperformance_threshold: float,
    min_group_size: int,
    *,
    previous_active_skill_keys: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Cluster students by shared underperforming skill dimensions.

    Algorithm
    ---------
    For each profile, iterate the ``skill_scores`` dict.  Any skill whose
    ``avg_score`` is strictly below *underperformance_threshold* is considered
    underperforming for that student.  Invert the mapping to build a dict from
    skill_key → list[student_id_str].  Filter out skills where the student
    count is below *min_group_size*.

    Stability
    ---------
    If *previous_active_skill_keys* is provided, each group is tagged:
    - ``'persistent'`` — skill_key existed (and was active) in the previous run.
    - ``'new'``        — skill_key is appearing for the first time.
    When *previous_active_skill_keys* is ``None``, all groups are marked ``'new'``.

    Returns a list of group dicts with keys:
      ``skill_key``, ``label``, ``student_ids``, ``student_count``,
      ``computed_at``, ``stability``.
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
    prev_keys = previous_active_skill_keys or set()

    groups: list[dict[str, Any]] = []
    for skill_key, student_id_strs in sorted(skill_students.items()):
        if len(student_id_strs) < min_group_size:
            continue
        label = skill_key.replace("_", " ").title()
        stability = "persistent" if skill_key in prev_keys else "new"
        groups.append(
            {
                "skill_key": skill_key,
                "label": label,
                "student_ids": sorted(student_id_strs),
                "student_count": len(student_id_strs),
                "computed_at": now_iso,
                "stability": stability,
            }
        )

    return groups


# ---------------------------------------------------------------------------
# Public service functions
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

    Stability tracking:
      Before clearing the existing groups, the service records which skill_keys
      currently have active (non-exited) groups.  After computing the new
      clusters, each new group is tagged 'persistent' (if its skill_key existed
      before) or 'new' (first appearance).  Skill_keys that were active but
      produced no new cluster (students improved or fell below *min_group_size*)
      are re-inserted as 'exited' rows with empty student lists, so the API can
      surface them as resolved gaps.

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

    # Snapshot active skill_keys before DELETE so we can compute stability.
    previous_active_skill_keys = await _load_existing_active_skill_keys(
        db, teacher_id, class_id
    )

    student_ids = await _load_enrolled_student_ids(db, class_id, teacher_id)

    profiles = await _load_skill_profiles(db, teacher_id, student_ids)

    groups = _build_groups(
        profiles,
        underperformance_threshold,
        min_group_size,
        previous_active_skill_keys=previous_active_skill_keys,
    )

    # Determine exited groups: skill_keys that were active before but produced
    # no new cluster in this computation run.
    new_skill_keys = {g["skill_key"] for g in groups}
    exited_skill_keys = previous_active_skill_keys - new_skill_keys

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

    persisted: list[StudentGroup] = []
    computed_at = datetime.now(UTC)
    try:
        await db.execute(
            delete(StudentGroup).where(
                StudentGroup.teacher_id == teacher_id,
                StudentGroup.class_id == class_id,
            )
        )

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
                    computed_at=computed_at,
                    stability=group["stability"],
                )
                .returning(StudentGroup)
            )
            result = await db.execute(stmt)
            row = result.scalar_one()
            persisted.append(row)

        # Insert exited groups — skill_keys that previously had active groups
        # but are no longer produced by the current computation.
        for exited_skill_key in sorted(exited_skill_keys):
            exited_label = exited_skill_key.replace("_", " ").title()
            stmt = (
                insert(StudentGroup)
                .values(
                    id=uuid.uuid4(),
                    teacher_id=teacher_id,
                    class_id=class_id,
                    skill_key=exited_skill_key,
                    label=exited_label,
                    student_ids=[],
                    student_count=0,
                    computed_at=computed_at,
                    stability="exited",
                )
                .returning(StudentGroup)
            )
            result = await db.execute(stmt)
            row = result.scalar_one()
            persisted.append(row)

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

    active_count = len([g for g in persisted if g.stability != "exited"])
    exited_count = len(exited_skill_keys)
    logger.info(
        "Auto-grouping complete",
        extra={
            "teacher_id": str(teacher_id),
            "class_id": str(class_id),
            "group_count": active_count,
            "exited_count": exited_count,
        },
    )

    return persisted


async def list_class_groups(
    db: AsyncSession,
    teacher_id: uuid.UUID,
    class_id: uuid.UUID,
) -> ClassGroupsResponse:
    """Return all current skill-gap groups for a class, with resolved student names.

    Fetches all ``StudentGroup`` rows for the given class (including 'exited'
    groups), resolves the student UUIDs stored in ``student_ids`` to full
    ``StudentInGroupResponse`` objects, and returns a ``ClassGroupsResponse``.

    Groups are ordered: active groups (new/persistent) first sorted by label,
    then exited groups sorted by label.

    Tenant isolation is enforced via ``teacher_id`` in every query; cross-teacher
    access raises :exc:`~app.exceptions.ForbiddenError`.

    Args:
        db:          Async database session.
        teacher_id:  UUID of the authenticated teacher.
        class_id:    UUID of the class whose groups to fetch.

    Returns:
        :class:`ClassGroupsResponse` with all groups.

    Raises:
        NotFoundError:  Class does not exist.
        ForbiddenError: Class belongs to a different teacher.
    """
    await _assert_class_owned_by(db, class_id, teacher_id)

    # Fetch all groups for this class, tenant-scoped.
    groups_result = await db.execute(
        select(StudentGroup).where(
            StudentGroup.teacher_id == teacher_id,
            StudentGroup.class_id == class_id,
        )
    )
    groups: list[StudentGroup] = list(groups_result.scalars().all())

    # Collect all unique student UUIDs referenced by active (non-exited) groups.
    all_student_id_strs: set[str] = set()
    for group in groups:
        if group.stability != "exited":
            all_student_id_strs.update(group.student_ids or [])

    # Batch-fetch student records for all referenced students, tenant-scoped.
    student_map: dict[str, StudentInGroupResponse] = {}
    if all_student_id_strs:
        try:
            student_uuids = [uuid.UUID(s) for s in all_student_id_strs]
        except ValueError:
            student_uuids = []

        if student_uuids:
            students_result = await db.execute(
                select(Student.id, Student.full_name, Student.external_id).where(
                    Student.teacher_id == teacher_id,
                    Student.id.in_(student_uuids),
                )
            )
            for row in students_result.all():
                student_map[str(row.id)] = StudentInGroupResponse(
                    id=row.id,
                    full_name=row.full_name,
                    external_id=row.external_id,
                )

    # Build response objects, ordering: active groups first (sorted by label),
    # then exited groups (sorted by label).
    active_groups: list[StudentGroupResponse] = []
    exited_groups: list[StudentGroupResponse] = []

    for group in groups:
        students_in_group: list[StudentInGroupResponse] = []
        if group.stability != "exited":
            for sid_str in sorted(group.student_ids or []):
                student = student_map.get(sid_str)
                if student is not None:
                    students_in_group.append(student)
            # Sort students by full_name for deterministic ordering.
            students_in_group.sort(key=lambda s: s.full_name)

        group_response = StudentGroupResponse(
            id=group.id,
            skill_key=group.skill_key,
            label=group.label,
            student_count=group.student_count,
            students=students_in_group,
            stability=group.stability,  # type: ignore[arg-type]
            computed_at=group.computed_at,
        )

        if group.stability == "exited":
            exited_groups.append(group_response)
        else:
            active_groups.append(group_response)

    active_groups.sort(key=lambda g: g.label)
    exited_groups.sort(key=lambda g: g.label)

    return ClassGroupsResponse(
        class_id=class_id,
        groups=active_groups + exited_groups,
    )
