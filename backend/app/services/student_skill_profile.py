"""StudentSkillProfile service.

Business logic for reading, upserting, and recomputing the per-student
skill-score aggregation introduced in M5-02 and M5-03.

Public API:
  - ``get_skill_profile``               — fetch the profile for a student (tenant-scoped).
  - ``upsert_skill_profile``            — insert or update the profile for a student,
                                          scoped to a specific teacher.
  - ``compute_and_upsert_skill_profile`` — load all locked criterion scores for a student,
                                          normalise to canonical skill dimensions, compute
                                          weighted-average / trend / data-point aggregates,
                                          and upsert the result into StudentSkillProfile.

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
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import ForbiddenError, NotFoundError
from app.models.assignment import Assignment
from app.models.class_ import Class
from app.models.essay import Essay, EssayVersion
from app.models.grade import CriterionScore, Grade
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

    Student ownership is first validated against ``teacher_id`` by
    ``_assert_student_owned_by()``, and the profile row itself is queried with
    a ``teacher_id`` filter so a teacher can never retrieve another teacher's
    profile.

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

    # Reload the full row with explicit tenant scoping for defense in depth.
    profile_result = await db.execute(
        select(StudentSkillProfile).where(
            StudentSkillProfile.id == returned_id,
            StudentSkillProfile.teacher_id == teacher_id,
            StudentSkillProfile.student_id == student_id,
        )
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


# ---------------------------------------------------------------------------
# Aggregation helpers
# ---------------------------------------------------------------------------

#: Trend thresholds — a score shift larger than this (in normalised 0-1 space)
#: is considered meaningful.
_TREND_THRESHOLD: float = 0.05


def _compute_trend(per_assignment_scores: list[float]) -> str:
    """Return ``"improving"``, ``"stable"``, or ``"declining"`` for a skill.

    Trend is computed by comparing the mean of the *first half* of assignments
    (ordered oldest-to-newest) against the mean of the *last half*.  When there
    is only one contributing assignment the trend is always ``"stable"`` because
    there is no longitudinal data to compare against.

    Args:
        per_assignment_scores: Per-assignment normalised scores for one skill
            dimension, ordered from oldest to newest assignment.

    Returns:
        One of the three trend label strings.
    """
    n = len(per_assignment_scores)
    if n < 2:
        return "stable"
    mid = n // 2
    first_avg = sum(per_assignment_scores[:mid]) / mid
    last_half = per_assignment_scores[mid:]
    last_avg = sum(last_half) / len(last_half)
    diff = last_avg - first_avg
    if diff > _TREND_THRESHOLD:
        return "improving"
    if diff < -_TREND_THRESHOLD:
        return "declining"
    return "stable"


def _aggregate_skill_scores(
    assignment_rows: list[dict[str, Any]],
) -> tuple[dict[str, Any], int]:
    """Aggregate per-assignment criterion scores into per-skill profile entries.

    Each row in *assignment_rows* represents one locked assignment and has the
    shape::

        {
            "locked_at": datetime,
            "rubric_snapshot": {"criteria": [{id, name, min_score, max_score, …}]},
            "criterion_scores": [(rubric_criterion_id: UUID, final_score: int), …],
        }

    The rows must be ordered from **oldest to newest** locked_at before being
    passed in — the ordering drives the recency-weighted average and the trend.

    Algorithm
    ---------
    1. For each assignment, look up criterion name from the rubric snapshot,
       normalise the name to a canonical skill dimension (via
       :func:`~app.services.skill_normalization.normalize_criterion_name`),
       and compute a per-criterion normalised score ``final_score / max_score``.
    2. Average the normalised scores for all criteria that map to the same
       skill within a single assignment → one float per (assignment, skill).
    3. Across assignments, compute a recency-weighted average where the weight
       of assignment *i* (0-indexed, 0 = oldest) is ``i + 1``.
    4. Compute trend from the per-assignment sequence.
    5. Count total individual criterion scores per skill (data_points).

    Returns:
        A tuple of (skill_scores_dict, assignment_count) where *skill_scores_dict*
        has the shape expected by :func:`upsert_skill_profile`.
    """
    # Lazy import to avoid circular dependency (skill_normalization imports
    # app.config which imports Celery task modules at registration time).
    from app.services.skill_normalization import normalize_criterion_name  # noqa: PLC0415

    # Per-assignment per-skill averaged normalised scores (oldest → newest).
    assignment_skill_averages: list[dict[str, float]] = []
    # Total individual criterion scores per skill (data_points).
    skill_data_points: dict[str, int] = defaultdict(int)

    for row in assignment_rows:
        snapshot: dict[str, Any] = row["rubric_snapshot"]
        criteria_list: list[dict[str, Any]] = snapshot.get("criteria", [])
        # Build criterion_id → criterion metadata map (using string keys because
        # rubric_criterion_id from the DB is a UUID, snapshot stores as str).
        criterion_map: dict[str, dict[str, Any]] = {c["id"]: c for c in criteria_list}

        skill_raw_scores: dict[str, list[float]] = defaultdict(list)

        for criterion_id, final_score in row["criterion_scores"]:
            crit = criterion_map.get(str(criterion_id))
            if crit is None:
                # Defensive: criterion was removed from snapshot after grading.
                continue
            max_score = int(crit.get("max_score", 1))
            min_score = int(crit.get("min_score", 0))
            score_range = max_score - min_score
            if score_range <= 0:
                normalised = 1.0
            else:
                normalised = (final_score - min_score) / score_range
                normalised = max(0.0, min(1.0, normalised))

            skill = normalize_criterion_name(crit["name"])
            skill_raw_scores[skill].append(normalised)
            skill_data_points[skill] += 1

        # Average within this assignment.
        assignment_skill_averages.append(
            {skill: sum(scores) / len(scores) for skill, scores in skill_raw_scores.items()}
        )

    # Collect all skill dimensions across every assignment.
    all_skills: set[str] = set()
    for asgn in assignment_skill_averages:
        all_skills.update(asgn.keys())

    now_str = datetime.now(UTC).isoformat()
    result: dict[str, Any] = {}

    for skill in sorted(all_skills):
        weighted_numerator = 0.0
        total_weight = 0.0
        per_asgn_scores: list[float] = []

        for i, asgn in enumerate(assignment_skill_averages):
            if skill not in asgn:
                continue
            weight = float(i + 1)  # recency weight: higher index → more recent
            weighted_numerator += weight * asgn[skill]
            total_weight += weight
            per_asgn_scores.append(asgn[skill])

        if total_weight == 0.0:
            continue  # skill had no scores (should not happen given all_skills filter)

        avg_score = weighted_numerator / total_weight
        trend = _compute_trend(per_asgn_scores)

        result[skill] = {
            "avg_score": round(avg_score, 4),
            "trend": trend,
            "data_points": skill_data_points[skill],
            "last_updated": now_str,
        }

    return result, len(assignment_rows)


# ---------------------------------------------------------------------------
# Compute-and-upsert public function
# ---------------------------------------------------------------------------


async def compute_and_upsert_skill_profile(
    db: AsyncSession,
    teacher_id: uuid.UUID,
    student_id: uuid.UUID,
) -> StudentSkillProfile:
    """Recompute the skill profile for a student from all their locked grades.

    Loads every locked :class:`~app.models.grade.Grade` for the student
    (scoped to *teacher_id*), normalises criterion names to canonical skill
    dimensions, and upserts the aggregated result into
    :class:`~app.models.student_skill_profile.StudentSkillProfile`.

    The operation is **idempotent** — calling it multiple times converges to
    the same result given the same locked grades.

    Security:
        All queries include *teacher_id* so a task cannot operate on another
        teacher's student data.  If the student does not exist, or if they
        exist but belong to a different teacher, the appropriate domain
        exception is raised before any data is read.

    Args:
        db:         Async database session.
        teacher_id: UUID of the teacher who owns the student.
        student_id: UUID of the student whose profile to recompute.

    Returns:
        The freshly upserted :class:`StudentSkillProfile` row.

    Raises:
        NotFoundError:  Student does not exist.
        ForbiddenError: Student belongs to a different teacher.
    """
    # Validate ownership first so we fail fast with the right error.
    await _assert_student_owned_by(db, student_id, teacher_id)

    # ------------------------------------------------------------------
    # Load all locked criterion scores for this student, tenant-scoped.
    # Each row carries (grade_id, locked_at, rubric_criterion_id,
    # final_score, rubric_snapshot).
    # ------------------------------------------------------------------
    rows_result = await db.execute(
        select(
            Grade.id.label("grade_id"),
            Grade.locked_at.label("locked_at"),
            CriterionScore.rubric_criterion_id,
            CriterionScore.final_score,
            Assignment.rubric_snapshot,
        )
        .join(CriterionScore, CriterionScore.grade_id == Grade.id)
        .join(EssayVersion, Grade.essay_version_id == EssayVersion.id)
        .join(Essay, EssayVersion.essay_id == Essay.id)
        .join(Assignment, Essay.assignment_id == Assignment.id)
        .join(Class, Assignment.class_id == Class.id)
        .where(
            Essay.student_id == student_id,
            Class.teacher_id == teacher_id,
            Grade.is_locked.is_(True),
        )
        .order_by(Grade.locked_at.asc())
    )
    raw_rows = rows_result.all()

    # ------------------------------------------------------------------
    # Group rows by grade (= assignment).
    # ------------------------------------------------------------------
    # Use an ordered dict keyed by grade_id to preserve locked_at order.
    assignment_map: dict[uuid.UUID, dict[str, Any]] = {}
    for row in raw_rows:
        gid: uuid.UUID = row.grade_id
        if gid not in assignment_map:
            assignment_map[gid] = {
                "locked_at": row.locked_at,
                "rubric_snapshot": row.rubric_snapshot,
                "criterion_scores": [],
            }
        assignment_map[gid]["criterion_scores"].append((row.rubric_criterion_id, row.final_score))

    # Sort by locked_at ascending (oldest → newest) for consistent weighting.
    assignment_rows = sorted(assignment_map.values(), key=lambda a: cast(datetime, a["locked_at"]))  # cast: mypy sees dict[str, Any]

    # ------------------------------------------------------------------
    # Aggregate and upsert.
    # ------------------------------------------------------------------
    skill_scores, assignment_count = _aggregate_skill_scores(assignment_rows)

    return await upsert_skill_profile(
        db,
        teacher_id,
        student_id,
        skill_scores=skill_scores,
        assignment_count=assignment_count,
    )
