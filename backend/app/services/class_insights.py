"""Class insights and assignment analytics service.

Implements the aggregation logic for:
- ``get_class_insights``         — class-level skill averages, score distributions,
                                   and common issues across all locked grades in a class.
- ``get_assignment_analytics``   — per-criterion breakdowns for a single assignment.

Design notes
------------
- All queries include ``teacher_id`` so a teacher can never access another
  teacher's data (tenant isolation).
- No student PII (names, essay content, raw feedback text) is emitted in logs.
  Only entity IDs appear in log output.
- Aggregations run in Python rather than SQL for portability and testability;
  typical class sizes (≤ 35 students, ≤ 6 assignments) keep result sets small.
- The skill-normalization layer (``app.services.skill_normalization``) is
  imported lazily to avoid circular import issues at module load time.
"""

from __future__ import annotations

import logging
import uuid
from collections import defaultdict
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import ForbiddenError, NotFoundError
from app.models.assignment import Assignment
from app.models.class_ import Class
from app.models.essay import Essay, EssayVersion
from app.models.grade import CriterionScore, Grade
from app.schemas.class_insights import (
    AssignmentAnalyticsResponse,
    ClassInsightsResponse,
    CommonIssue,
    CriterionAnalytics,
    ScoreBucket,
    ScoreCount,
    SkillAverage,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Normalised score below which a skill is considered a "common issue".
_CONCERN_THRESHOLD: float = 0.60

#: Histogram bucket boundaries (0.0, 0.2, 0.4, 0.6, 0.8, 1.0+).
_BUCKET_EDGES: list[float] = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]
_BUCKET_LABELS: list[str] = ["0-20%", "20-40%", "40-60%", "60-80%", "80-100%"]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _assert_class_owned_by(
    db: AsyncSession,
    class_id: uuid.UUID,
    teacher_id: uuid.UUID,
) -> None:
    """Verify that the class exists and belongs to the given teacher.

    Raises :exc:`NotFoundError` if the class does not exist.
    Raises :exc:`ForbiddenError` if the class belongs to a different teacher.
    """
    result = await db.execute(select(Class.id, Class.teacher_id).where(Class.id == class_id))
    row = result.one_or_none()
    if row is None:
        raise NotFoundError("Class not found.")
    if row.teacher_id != teacher_id:
        raise ForbiddenError("You do not have access to this class.")


async def _assert_assignment_owned_by(
    db: AsyncSession,
    assignment_id: uuid.UUID,
    teacher_id: uuid.UUID,
) -> Assignment:
    """Verify that the assignment exists and belongs to the given teacher.

    Returns the full Assignment ORM object for the owning teacher.
    Raises :exc:`NotFoundError` if the assignment does not exist.
    Raises :exc:`ForbiddenError` if the assignment belongs to a different teacher.
    """
    # First: check existence without tenant filter so we can distinguish
    # "not found" from "forbidden".
    exists_result = await db.execute(select(Assignment.id).where(Assignment.id == assignment_id))
    if exists_result.one_or_none() is None:
        raise NotFoundError("Assignment not found.")

    # Second: load the full row enforcing teacher_id at the query level.
    assignment_result = await db.execute(
        select(Assignment)
        .join(Class, Assignment.class_id == Class.id)
        .where(
            Assignment.id == assignment_id,
            Class.teacher_id == teacher_id,
        )
    )
    assignment = assignment_result.scalar_one_or_none()
    if assignment is None:
        raise ForbiddenError("You do not have access to this assignment.")
    return assignment


def _normalise_score(final_score: int, min_score: int, max_score: int) -> float:
    """Return a normalised score in [0.0, 1.0].

    When ``max_score == min_score`` (degenerate rubric criterion) the result is
    always 1.0 (full credit) to avoid division by zero.
    """
    score_range = max_score - min_score
    if score_range <= 0:
        return 1.0
    normalised = (final_score - min_score) / score_range
    return max(0.0, min(1.0, normalised))


def _bucket_index(normalised: float) -> int:
    """Return the 0-based histogram bucket index for a normalised score."""
    if normalised >= 1.0:
        return len(_BUCKET_LABELS) - 1
    for i, edge in enumerate(_BUCKET_EDGES[1:], start=1):
        if normalised < edge:
            return i - 1
    return len(_BUCKET_LABELS) - 1


def _build_distribution(normalised_scores: list[float]) -> list[ScoreBucket]:
    """Build a 5-bucket score distribution from a list of normalised scores."""
    counts = [0] * len(_BUCKET_LABELS)
    for score in normalised_scores:
        counts[_bucket_index(score)] += 1
    return [
        ScoreBucket(label=label, count=count)
        for label, count in zip(_BUCKET_LABELS, counts, strict=True)
    ]


# ---------------------------------------------------------------------------
# Public service functions
# ---------------------------------------------------------------------------


async def get_class_insights(
    db: AsyncSession,
    teacher_id: uuid.UUID,
    class_id: uuid.UUID,
) -> ClassInsightsResponse:
    """Compute class-level skill averages, score distributions, and common issues.

    Loads all locked criterion scores for every assignment in the class, normalises
    criterion names to canonical skill dimensions, and aggregates across the class.

    Tenant isolation:
        The query includes ``teacher_id`` via the Class join so a teacher can only
        see data for their own class.

    Args:
        db:         Async database session.
        teacher_id: UUID of the authenticated teacher.
        class_id:   UUID of the class to analyse.

    Returns:
        A :class:`ClassInsightsResponse` with aggregated analytics.

    Raises:
        NotFoundError:  Class does not exist.
        ForbiddenError: Class belongs to a different teacher.
    """
    from app.services.skill_normalization import normalize_criterion_name  # noqa: PLC0415

    await _assert_class_owned_by(db, class_id, teacher_id)

    # ------------------------------------------------------------------
    # Count assignments and students in the class.
    # ------------------------------------------------------------------
    assignment_count_result = await db.execute(
        select(func.count(Assignment.id)).where(
            Assignment.class_id == class_id,
        )
    )
    assignment_count: int = assignment_count_result.scalar_one()

    # Count distinct actively enrolled students.
    from app.models.class_enrollment import ClassEnrollment  # noqa: PLC0415

    student_count_result = await db.execute(
        select(func.count(ClassEnrollment.student_id)).where(
            ClassEnrollment.class_id == class_id,
            ClassEnrollment.removed_at.is_(None),
        )
    )
    student_count: int = student_count_result.scalar_one()

    # ------------------------------------------------------------------
    # Load all locked criterion scores for the class (tenant-scoped).
    # Each row carries (essay_student_id, rubric_criterion_id, final_score,
    # rubric_snapshot, grade_id).
    # ------------------------------------------------------------------
    rows_result = await db.execute(
        select(
            Essay.id.label("essay_id"),
            Essay.student_id.label("student_id"),
            Grade.id.label("grade_id"),
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
            Assignment.class_id == class_id,
            Class.teacher_id == teacher_id,
            Grade.is_locked.is_(True),
        )
    )
    raw_rows = rows_result.all()

    # ------------------------------------------------------------------
    # Aggregate per skill dimension (single pass).
    # ------------------------------------------------------------------
    # skill → list of normalised scores (one per criterion score row)
    skill_normalised_scores: dict[str, list[float]] = defaultdict(list)
    # skill → set of student UUIDs (None excluded) that contributed ≥1 score
    skill_student_sets: dict[str, set[uuid.UUID]] = defaultdict(set)
    # student_id → skill → [normalised_score, ...]  (None student_id excluded)
    student_skill_scores: dict[uuid.UUID, dict[str, list[float]]] = defaultdict(
        lambda: defaultdict(list)
    )
    # Track distinct essay IDs (not grade IDs) for graded_essay_count.
    graded_essay_ids: set[uuid.UUID] = set()

    for row in raw_rows:
        graded_essay_ids.add(row.essay_id)
        snapshot: dict[str, Any] = row.rubric_snapshot
        criteria_list: list[dict[str, Any]] = snapshot.get("criteria", [])
        criterion_map: dict[str, dict[str, Any]] = {c["id"]: c for c in criteria_list}

        crit = criterion_map.get(str(row.rubric_criterion_id))
        if crit is None:
            continue

        max_score = int(crit.get("max_score", 1))
        min_score = int(crit.get("min_score", 0))
        normalised = _normalise_score(row.final_score, min_score, max_score)
        skill = normalize_criterion_name(crit["name"])

        skill_normalised_scores[skill].append(normalised)

        # Only include rows with an assigned student in student-based aggregates.
        if row.student_id is not None:
            skill_student_sets[skill].add(row.student_id)
            student_skill_scores[row.student_id][skill].append(normalised)

    # ------------------------------------------------------------------
    # Build response components.
    # ------------------------------------------------------------------
    skill_averages: dict[str, SkillAverage] = {}
    score_distributions: dict[str, list[ScoreBucket]] = {}
    common_issues: list[CommonIssue] = []

    for skill in sorted(skill_normalised_scores.keys()):
        scores = skill_normalised_scores[skill]
        avg = sum(scores) / len(scores)

        skill_averages[skill] = SkillAverage(
            avg_score=round(avg, 4),
            student_count=len(skill_student_sets[skill]),
            data_points=len(scores),
        )
        score_distributions[skill] = _build_distribution(scores)

    for skill, avg_obj in skill_averages.items():
        if avg_obj.avg_score < _CONCERN_THRESHOLD:
            affected = sum(
                1
                for per_skill in student_skill_scores.values()
                if skill in per_skill
                and (sum(per_skill[skill]) / len(per_skill[skill])) < _CONCERN_THRESHOLD
            )
            common_issues.append(
                CommonIssue(
                    skill_dimension=skill,
                    avg_score=avg_obj.avg_score,
                    affected_student_count=affected,
                )
            )

    # Sort common issues by ascending avg_score (worst first).
    common_issues.sort(key=lambda ci: ci.avg_score)

    logger.info(
        "Class insights computed",
        extra={
            "class_id": str(class_id),
            "teacher_id": str(teacher_id),
            "graded_essay_count": len(graded_essay_ids),
        },
    )

    return ClassInsightsResponse(
        class_id=class_id,
        assignment_count=assignment_count,
        student_count=student_count,
        graded_essay_count=len(graded_essay_ids),
        skill_averages=skill_averages,
        score_distributions=score_distributions,
        common_issues=common_issues,
    )


async def get_assignment_analytics(
    db: AsyncSession,
    teacher_id: uuid.UUID,
    assignment_id: uuid.UUID,
) -> AssignmentAnalyticsResponse:
    """Compute per-criterion analytics for a single assignment.

    Loads all locked criterion scores for the assignment, groups them by
    rubric criterion, and computes average, normalised average, and score
    distribution for each criterion.

    Tenant isolation:
        Ownership is checked via the Class.teacher_id join in
        ``_assert_assignment_owned_by``.  The criterion score query further
        includes a join back through Class to enforce teacher_id.

    Args:
        db:            Async database session.
        teacher_id:    UUID of the authenticated teacher.
        assignment_id: UUID of the assignment to analyse.

    Returns:
        An :class:`AssignmentAnalyticsResponse` with criterion-level breakdowns.

    Raises:
        NotFoundError:  Assignment does not exist.
        ForbiddenError: Assignment belongs to a different teacher.
    """
    from app.services.skill_normalization import normalize_criterion_name  # noqa: PLC0415

    assignment = await _assert_assignment_owned_by(db, assignment_id, teacher_id)

    # ------------------------------------------------------------------
    # Count total essays and locked essays.
    # ------------------------------------------------------------------
    total_count_result = await db.execute(
        select(func.count(Essay.id)).where(Essay.assignment_id == assignment_id)
    )
    total_essay_count: int = total_count_result.scalar_one()

    locked_count_result = await db.execute(
        select(func.count(func.distinct(Essay.id)))
        .join(EssayVersion, Grade.essay_version_id == EssayVersion.id)
        .join(Essay, EssayVersion.essay_id == Essay.id)
        .where(
            Essay.assignment_id == assignment_id,
            Grade.is_locked.is_(True),
        )
    )
    locked_essay_count: int = locked_count_result.scalar_one()

    # ------------------------------------------------------------------
    # Load locked criterion scores (tenant-scoped via Class join).
    # ------------------------------------------------------------------
    scores_result = await db.execute(
        select(
            CriterionScore.rubric_criterion_id,
            CriterionScore.final_score,
        )
        .join(Grade, CriterionScore.grade_id == Grade.id)
        .join(EssayVersion, Grade.essay_version_id == EssayVersion.id)
        .join(Essay, EssayVersion.essay_id == Essay.id)
        .join(Assignment, Essay.assignment_id == Assignment.id)
        .join(Class, Assignment.class_id == Class.id)
        .where(
            Essay.assignment_id == assignment_id,
            Class.teacher_id == teacher_id,
            Grade.is_locked.is_(True),
        )
    )
    score_rows = scores_result.all()

    # ------------------------------------------------------------------
    # Group scores by criterion_id.
    # ------------------------------------------------------------------
    criterion_scores_map: dict[str, list[int]] = defaultdict(list)
    for row in score_rows:
        criterion_scores_map[str(row.rubric_criterion_id)].append(row.final_score)

    # ------------------------------------------------------------------
    # Build per-criterion analytics from rubric snapshot.
    # ------------------------------------------------------------------
    snapshot: dict[str, Any] = assignment.rubric_snapshot
    criteria_list: list[dict[str, Any]] = snapshot.get("criteria", [])
    # Respect display_order if present.
    criteria_list = sorted(criteria_list, key=lambda c: c.get("display_order", 0))

    criterion_analytics: list[CriterionAnalytics] = []
    all_normalised_scores: list[float] = []

    for crit in criteria_list:
        crit_id_str = crit.get("id", "")
        crit_name = crit.get("name", "")
        min_score = int(crit.get("min_score", 0))
        max_score = int(crit.get("max_score", 1))
        skill = normalize_criterion_name(crit_name)

        raw_scores = criterion_scores_map.get(crit_id_str, [])

        if not raw_scores:
            # No locked grades for this criterion yet; include with zeros.
            criterion_analytics.append(
                CriterionAnalytics(
                    criterion_id=uuid.UUID(crit_id_str) if crit_id_str else uuid.uuid4(),
                    criterion_name=crit_name,
                    skill_dimension=skill,
                    min_score_possible=min_score,
                    max_score_possible=max_score,
                    avg_score=0.0,
                    avg_normalized_score=0.0,
                    score_distribution=[],
                )
            )
            continue

        avg_raw = sum(raw_scores) / len(raw_scores)
        normalised_scores = [_normalise_score(s, min_score, max_score) for s in raw_scores]
        avg_normalised = sum(normalised_scores) / len(normalised_scores)
        all_normalised_scores.extend(normalised_scores)

        # Build raw score distribution.
        score_freq: dict[int, int] = defaultdict(int)
        for s in raw_scores:
            score_freq[s] += 1
        score_distribution = [
            ScoreCount(score=score, count=cnt) for score, cnt in sorted(score_freq.items())
        ]

        criterion_analytics.append(
            CriterionAnalytics(
                criterion_id=uuid.UUID(crit_id_str) if crit_id_str else uuid.uuid4(),
                criterion_name=crit_name,
                skill_dimension=skill,
                min_score_possible=min_score,
                max_score_possible=max_score,
                avg_score=round(avg_raw, 4),
                avg_normalized_score=round(avg_normalised, 4),
                score_distribution=score_distribution,
            )
        )

    overall_avg: float | None = (
        round(sum(all_normalised_scores) / len(all_normalised_scores), 4)
        if all_normalised_scores
        else None
    )

    logger.info(
        "Assignment analytics computed",
        extra={
            "assignment_id": str(assignment_id),
            "teacher_id": str(teacher_id),
            "locked_essay_count": locked_essay_count,
        },
    )

    return AssignmentAnalyticsResponse(
        assignment_id=assignment_id,
        class_id=assignment.class_id,
        total_essay_count=total_essay_count,
        locked_essay_count=locked_essay_count,
        overall_avg_normalized_score=overall_avg,
        criterion_analytics=criterion_analytics,
    )
