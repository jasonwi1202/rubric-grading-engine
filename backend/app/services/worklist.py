"""Teacher worklist generation service (M6-04).

Generates a ranked, teacher-facing worklist from four student profile signals:

1. **regression**         — A skill dimension is trending downward
                            (``trend == 'declining'``).  Urgency 4.
2. **non_responder**      — A student resubmitted an essay but improved by
                            less than :data:`_NON_RESPONDER_IMPROVEMENT_THRESHOLD`.
                            Indicates that written feedback alone is not working.
                            Urgency 4.
3. **persistent_gap**     — A skill dimension is chronically below
                            :data:`_GAP_SCORE_THRESHOLD` across ≥
                            :data:`_GAP_MIN_ASSIGNMENTS` assignments with a
                            non-improving trend.  Also fires when the student is
                            in a ``'persistent'`` :class:`StudentGroup` for that
                            skill.  Urgency 3.
4. **high_inconsistency** — A skill dimension shows a population standard
                            deviation above :data:`_INCONSISTENCY_STD_THRESHOLD`
                            across ≥ :data:`_INCONSISTENCY_MIN_ASSIGNMENTS`
                            assignments, suggesting unstable or context-sensitive
                            skill.  Urgency 2.

Public API:
  - :func:`generate_teacher_worklist`      — compute ranked items (read-only).
  - :func:`compute_and_persist_worklist`   — compute + atomically replace
                                             active items in the DB.

Pure helper functions (no DB calls, unit-testable in isolation):
  - :func:`_check_regression`
  - :func:`_check_persistent_gap`
  - :func:`_check_high_inconsistency`
  - :func:`_check_non_responder`
  - :func:`_rank_items`

Tenant isolation:
  All queries include ``teacher_id``.  No student PII (names, essay content,
  raw scores) appears in log statements — only entity IDs.

Determinism:
  Given the same DB state, both public functions return the same ranked list.
  Urgency ties are broken deterministically by trigger type order
  (regression → non_responder → persistent_gap → high_inconsistency) then
  by ``skill_key`` alphabetically (``None`` sorts before any string value so
  student-level triggers appear first within the same urgency tier).
"""

from __future__ import annotations

import logging
import math
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import case, delete, insert, nulls_first, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.assignment import Assignment
from app.models.class_ import Class
from app.models.essay import Essay, EssayVersion
from app.models.grade import CriterionScore, Grade
from app.models.student_group import StudentGroup
from app.models.student_skill_profile import StudentSkillProfile
from app.models.user import User
from app.models.worklist import TeacherWorklistItem

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Thresholds and urgency constants
# ---------------------------------------------------------------------------

#: Normalised skill avg_score (0–1) below which a student is underperforming.
_GAP_SCORE_THRESHOLD: float = 0.60

#: Minimum locked-assignment count before the persistent_gap trigger is eligible.
_GAP_MIN_ASSIGNMENTS: int = 2

#: Population std deviation of per-assignment normalised scores above which
#: high_inconsistency fires.
_INCONSISTENCY_STD_THRESHOLD: float = 0.20

#: Minimum number of per-assignment data points required to compute a
#: meaningful standard deviation for the high_inconsistency check.
_INCONSISTENCY_MIN_ASSIGNMENTS: int = 3

#: Minimum normalised score improvement (resubmission − original) required
#: to avoid the non_responder trigger.  Improvements below this threshold
#: (including zero or negative change) indicate the student did not respond
#: meaningfully to written feedback.
_NON_RESPONDER_IMPROVEMENT_THRESHOLD: float = 0.05

#: Urgency assigned to the ``regression`` trigger.
_URGENCY_REGRESSION: int = 4
#: Urgency assigned to the ``non_responder`` trigger.
_URGENCY_NON_RESPONDER: int = 4
#: Urgency assigned to the ``persistent_gap`` trigger.
_URGENCY_PERSISTENT_GAP: int = 3
#: Urgency assigned to the ``high_inconsistency`` trigger.
_URGENCY_HIGH_INCONSISTENCY: int = 2

#: Ordering of trigger types for deterministic tie-breaking within the same
#: urgency level.  Lower index = appears first in the ranked list.
_TRIGGER_ORDER: dict[str, int] = {
    "regression": 0,
    "non_responder": 1,
    "persistent_gap": 2,
    "high_inconsistency": 3,
}


def _trigger_order_case_expr() -> object:
    """Return a SQLAlchemy CASE expression for deterministic trigger-type ordering.

    Produces the same ordering used by :func:`_rank_items` so that DB queries
    return rows in the identical sequence to the in-memory sort.  Both
    :func:`compute_and_persist_worklist` and :func:`get_worklist_for_teacher`
    use this helper to avoid duplicating the mapping.
    """
    return case(
        _TRIGGER_ORDER,
        value=TeacherWorklistItem.trigger_type,
        else_=99,
    )


# ---------------------------------------------------------------------------
# Internal data structure
# ---------------------------------------------------------------------------


@dataclass
class _WorklistItemData:
    """Computed (in-memory) worklist item before DB persistence."""

    student_id: uuid.UUID
    trigger_type: str
    skill_key: str | None
    urgency: int
    suggested_action: str
    details: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Suggested-action strings
# ---------------------------------------------------------------------------


def _suggested_action(trigger_type: str, skill_key: str | None) -> str:
    """Return a deterministic, concrete action string for a trigger.

    All suggestions are intentionally concrete and achievable within typical
    classroom constraints.  The same (trigger_type, skill_key) pair always
    produces the same string.

    Args:
        trigger_type: One of ``'regression'``, ``'persistent_gap'``,
                      ``'high_inconsistency'``, ``'non_responder'``.
        skill_key:    Canonical skill dimension key, or ``None`` for
                      student-level triggers.

    Returns:
        A plain-text action suggestion for the teacher.
    """
    skill_label = skill_key.replace("_", " ") if skill_key else ""
    match trigger_type:
        case "regression":
            return (
                f"Review the recent decline in {skill_label} with this student "
                f"and identify what changed."
            )
        case "persistent_gap":
            return f"Assign a targeted practice exercise focused on {skill_label}."
        case "high_inconsistency":
            return (
                f"Review the last 3 essays together to identify what causes "
                f"score variability in {skill_label}."
            )
        case "non_responder":
            return (
                "Schedule a 1:1 check-in to understand why written feedback "
                "has not translated to improvement."
            )
        case _:
            return "Follow up with this student."


# ---------------------------------------------------------------------------
# Pure trigger-check functions (no DB, fully unit-testable)
# ---------------------------------------------------------------------------


def _check_regression(
    profile: StudentSkillProfile,
) -> list[_WorklistItemData]:
    """Fire once per skill dimension with ``trend == 'declining'``.

    The trend in the stored skill profile already captures whether the mean of
    the most recent assignments is meaningfully lower than the mean of the
    earlier ones (see ``_compute_trend`` in the student_skill_profile service).
    At least two data points are required by that function before a 'declining'
    trend is assigned, so single-assignment profiles cannot fire this trigger.

    Args:
        profile: The student's aggregated skill profile.

    Returns:
        One :class:`_WorklistItemData` per skill dimension with a declining
        trend, sorted alphabetically by skill_key for determinism.
    """
    items: list[_WorklistItemData] = []
    skill_scores: dict[str, Any] = profile.skill_scores or {}
    for skill_key, entry in sorted(skill_scores.items()):
        if not isinstance(entry, dict):
            continue
        if entry.get("trend") == "declining":
            items.append(
                _WorklistItemData(
                    student_id=profile.student_id,
                    trigger_type="regression",
                    skill_key=skill_key,
                    urgency=_URGENCY_REGRESSION,
                    suggested_action=_suggested_action("regression", skill_key),
                    details={
                        "avg_score": entry.get("avg_score"),
                        "trend": "declining",
                    },
                )
            )
    return items


def _check_persistent_gap(
    profile: StudentSkillProfile,
    persistent_skill_keys: set[str],
) -> list[_WorklistItemData]:
    """Fire for each skill dimension with a persistent underperformance signal.

    A persistent gap fires when **either** (or both) of the following are true:

    1. The student is a member of a :class:`~app.models.student_group.StudentGroup`
       with ``stability='persistent'`` for this ``skill_key`` — they have been
       flagged in the same group across ≥ 2 auto-grouping runs.
    2. The skill's ``avg_score < _GAP_SCORE_THRESHOLD`` **AND**
       ``profile.assignment_count >= _GAP_MIN_ASSIGNMENTS`` **AND**
       the trend is not ``'improving'``.

    The two conditions overlap but capture slightly different signals:

    - Group persistence captures *class-relative* underperformance.
    - The score-threshold condition captures *absolute* individual underperformance
      even for students not in any group (e.g. a class where everyone underperforms
      so no group forms).

    Args:
        profile:               Aggregated skill profile for the student.
        persistent_skill_keys: Set of skill dimension keys for which this student
                                is currently in a ``'persistent'`` StudentGroup.

    Returns:
        One :class:`_WorklistItemData` per skill meeting either condition, sorted
        alphabetically by skill_key.
    """
    items: list[_WorklistItemData] = []
    skill_scores: dict[str, Any] = profile.skill_scores or {}
    for skill_key, entry in sorted(skill_scores.items()):
        if not isinstance(entry, dict):
            continue
        avg_score = entry.get("avg_score")
        trend = entry.get("trend", "stable")
        if not isinstance(avg_score, (int, float)):
            continue

        in_persistent_group = skill_key in persistent_skill_keys
        below_threshold = float(avg_score) < _GAP_SCORE_THRESHOLD
        enough_assignments = profile.assignment_count >= _GAP_MIN_ASSIGNMENTS
        not_improving = trend != "improving"

        if in_persistent_group or (below_threshold and enough_assignments and not_improving):
            items.append(
                _WorklistItemData(
                    student_id=profile.student_id,
                    trigger_type="persistent_gap",
                    skill_key=skill_key,
                    urgency=_URGENCY_PERSISTENT_GAP,
                    suggested_action=_suggested_action("persistent_gap", skill_key),
                    details={
                        "avg_score": round(float(avg_score), 4),
                        "trend": trend,
                        "in_persistent_group": in_persistent_group,
                    },
                )
            )
    return items


def _check_high_inconsistency(
    student_id: uuid.UUID,
    per_assignment_skill_scores: dict[str, list[float]],
) -> list[_WorklistItemData]:
    """Fire for each skill dimension with high per-assignment score variance.

    Computes the population standard deviation of the per-assignment normalised
    scores for each skill dimension.  The trigger fires when:
    - There are ≥ :data:`_INCONSISTENCY_MIN_ASSIGNMENTS` data points, AND
    - The std deviation exceeds :data:`_INCONSISTENCY_STD_THRESHOLD`.

    Population std deviation (not sample std deviation) is used for determinism
    and because the goal is to characterise the observed spread, not to infer
    a population parameter.

    Args:
        student_id:                  UUID of the student.
        per_assignment_skill_scores: Mapping of ``skill_key → [score_asgn_0,
                                      …, score_asgn_n]``, ordered oldest first.
                                      Each score is a normalised value in [0, 1].

    Returns:
        One :class:`_WorklistItemData` per skill with high inconsistency, sorted
        alphabetically by skill_key.
    """
    items: list[_WorklistItemData] = []
    for skill_key, scores in sorted(per_assignment_skill_scores.items()):
        n = len(scores)
        if n < _INCONSISTENCY_MIN_ASSIGNMENTS:
            continue
        mean = sum(scores) / n
        variance = sum((s - mean) ** 2 for s in scores) / n
        std = math.sqrt(variance)
        if std > _INCONSISTENCY_STD_THRESHOLD:
            items.append(
                _WorklistItemData(
                    student_id=student_id,
                    trigger_type="high_inconsistency",
                    skill_key=skill_key,
                    urgency=_URGENCY_HIGH_INCONSISTENCY,
                    suggested_action=_suggested_action("high_inconsistency", skill_key),
                    details={
                        "std_dev": round(std, 4),
                        "assignment_count": n,
                    },
                )
            )
    return items


def _check_non_responder(
    student_id: uuid.UUID,
    resubmission_pairs: list[tuple[float, float]],
) -> list[_WorklistItemData]:
    """Fire if any resubmission shows insufficient improvement.

    A student is a non-responder for a resubmission when the normalised total
    score improvement from the original version (v1) to the best resubmission
    score is less than :data:`_NON_RESPONDER_IMPROVEMENT_THRESHOLD`.

    At most **one** non_responder item is generated per student (it is a
    student-level trigger, not skill-specific).  If multiple resubmissions exist
    and any one fails the improvement threshold, the trigger fires once.

    Args:
        student_id:          UUID of the student.
        resubmission_pairs:  List of ``(original_norm, resubmission_norm)``
                              tuples.  Each tuple represents one essay that was
                              resubmitted.  Scores are normalised to [0, 1].

    Returns:
        A list with zero or one :class:`_WorklistItemData`.
    """
    for original_norm, resubmission_norm in resubmission_pairs:
        improvement = resubmission_norm - original_norm
        if improvement < _NON_RESPONDER_IMPROVEMENT_THRESHOLD:
            return [
                _WorklistItemData(
                    student_id=student_id,
                    trigger_type="non_responder",
                    skill_key=None,
                    urgency=_URGENCY_NON_RESPONDER,
                    suggested_action=_suggested_action("non_responder", None),
                    details={
                        "improvement": round(improvement, 4),
                        "resubmission_count": len(resubmission_pairs),
                    },
                )
            ]
    return []


def _rank_items(items: list[_WorklistItemData]) -> list[_WorklistItemData]:
    """Sort worklist items by urgency descending, then by trigger type, then skill_key.

    Descending urgency ensures the most urgent items appear first.  Ties are
    broken deterministically:

    1. ``trigger_type`` ordering: regression → non_responder → persistent_gap →
       high_inconsistency (matches urgency order within same-urgency pairs).
    2. ``skill_key`` alphabetically; ``None`` maps to ``''`` and sorts before
       any non-empty skill key, so student-level triggers (non_responder)
       appear first among items sharing the same urgency tier.
    3. ``student_id`` as a final tiebreaker so that items with identical
       urgency, trigger type, and skill key are sorted in a stable, repeatable
       order regardless of the order that DB rows were returned.

    Args:
        items: Unordered list of computed worklist items.

    Returns:
        The same items, re-ordered.
    """
    return sorted(
        items,
        key=lambda item: (
            -item.urgency,
            _TRIGGER_ORDER.get(item.trigger_type, 99),
            item.skill_key or "",
            str(item.student_id),
        ),
    )


# ---------------------------------------------------------------------------
# DB-loading helpers
# ---------------------------------------------------------------------------


async def _load_skill_profiles(
    db: AsyncSession,
    teacher_id: uuid.UUID,
) -> list[StudentSkillProfile]:
    """Load all StudentSkillProfile rows owned by *teacher_id*."""
    result = await db.execute(
        select(StudentSkillProfile).where(
            StudentSkillProfile.teacher_id == teacher_id,
        )
    )
    return list(result.scalars().all())


async def _load_persistent_group_memberships(
    db: AsyncSession,
    teacher_id: uuid.UUID,
) -> dict[uuid.UUID, set[str]]:
    """Return a mapping of student_id → set of persistently-flagged skill keys.

    Reads all :class:`~app.models.student_group.StudentGroup` rows with
    ``stability='persistent'`` for the teacher and inverts the ``student_ids``
    JSONB array to build a per-student set of persistently-underperforming skills.

    Tenant isolation: ``teacher_id`` filter on ``StudentGroup`` ensures only
    the authenticated teacher's groups are read.

    Args:
        db:         Async database session.
        teacher_id: UUID of the authenticated teacher.

    Returns:
        Mapping of student UUID → set of skill_key strings where the student
        is in a persistent group.  Students not in any persistent group are
        absent from the mapping (use ``dict.get(sid, set())``).
    """
    result = await db.execute(
        select(StudentGroup.skill_key, StudentGroup.student_ids).where(
            StudentGroup.teacher_id == teacher_id,
            StudentGroup.stability == "persistent",
        )
    )
    rows = result.all()

    memberships: dict[uuid.UUID, set[str]] = defaultdict(set)
    for row in rows:
        for student_id_str in row.student_ids:
            try:
                sid = uuid.UUID(student_id_str)
            except ValueError:
                continue
            memberships[sid].add(row.skill_key)
    return dict(memberships)


async def _load_per_assignment_skill_scores_for_all_students(
    db: AsyncSession,
    teacher_id: uuid.UUID,
) -> dict[uuid.UUID, dict[str, list[float]]]:
    """Load per-assignment normalised scores per skill for all teacher's students.

    Executes a single JOIN query across grades, essay versions, essays,
    assignments, and classes to load all locked criterion scores for every
    student of *teacher_id*.  Results are grouped and normalised in Python.

    Returns:
        Mapping of ``student_id → {skill_key → [score_oldest, …, score_newest]}``.
        Only students with at least one locked grade appear in the result.

    Tenant isolation:
        The query joins through ``Class.teacher_id`` so only the authenticated
        teacher's data is returned.

    No student PII appears in this function or its log output.
    """
    from app.services.skill_normalization import normalize_criterion_name  # noqa: PLC0415
    # Deferred to avoid circular-import issues during module initialisation.
    # Python caches the module after the first import so the repeated calls
    # inside the loop incur no additional overhead.

    rows_result = await db.execute(
        select(
            Essay.student_id,
            Grade.id.label("grade_id"),
            Grade.locked_at,
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
            Class.teacher_id == teacher_id,
            Grade.is_locked.is_(True),
            Grade.locked_at.is_not(None),
            Essay.student_id.is_not(None),
        )
        .order_by(Essay.student_id, Grade.locked_at.asc(), Grade.id.asc())
    )
    raw_rows = rows_result.all()

    # Group by (student_id, grade_id) → criterion scores.
    student_assignment_map: dict[uuid.UUID, dict[uuid.UUID, dict[str, Any]]] = defaultdict(
        dict
    )
    for row in raw_rows:
        student_id = cast(uuid.UUID, row.student_id)
        grade_id = cast(uuid.UUID, row.grade_id)
        if grade_id not in student_assignment_map[student_id]:
            student_assignment_map[student_id][grade_id] = {
                "locked_at": row.locked_at,
                "rubric_snapshot": row.rubric_snapshot,
                "criterion_scores": [],
            }
        student_assignment_map[student_id][grade_id]["criterion_scores"].append(
            (row.rubric_criterion_id, row.final_score)
        )

    # Build per-student per-skill assignment sequences.
    result: dict[uuid.UUID, dict[str, list[float]]] = {}
    for student_id, grade_map in student_assignment_map.items():
        # Sort assignments oldest → newest for consistent ordering.
        sorted_assignments = sorted(
            grade_map.values(), key=lambda a: cast(datetime, a["locked_at"])
        )

        per_skill_sequences: dict[str, list[float]] = defaultdict(list)

        for asgn in sorted_assignments:
            snapshot: dict[str, Any] = asgn["rubric_snapshot"]
            criteria_list: list[dict[str, Any]] = snapshot.get("criteria", [])
            criterion_map: dict[str, dict[str, Any]] = {c["id"]: c for c in criteria_list}

            skill_raw_scores: dict[str, list[float]] = defaultdict(list)
            for criterion_id, final_score in asgn["criterion_scores"]:
                crit = criterion_map.get(str(criterion_id))
                if crit is None:
                    continue
                max_s = int(crit.get("max_score", 1))
                min_s = int(crit.get("min_score", 0))
                score_range = max_s - min_s
                if score_range <= 0:
                    # A zero-range criterion has min_score == max_score, meaning
                    # all possible scores are equivalent.  Treat as fully achieved
                    # so the criterion contributes no variance to the skill average.
                    normalised = 1.0
                else:
                    normalised = max(0.0, min(1.0, (final_score - min_s) / score_range))
                skill = normalize_criterion_name(crit["name"])
                skill_raw_scores[skill].append(normalised)

            # Average across criteria within this assignment, then append to sequence.
            for skill, scores in skill_raw_scores.items():
                per_skill_sequences[skill].append(sum(scores) / len(scores))

        result[student_id] = dict(per_skill_sequences)
    return result


async def _load_resubmission_pairs_for_all_students(
    db: AsyncSession,
    teacher_id: uuid.UUID,
) -> dict[uuid.UUID, list[tuple[float, float]]]:
    """Load (original_norm, best_resubmission_norm) pairs for each student.

    A resubmission pair exists when a student's essay has:
    - A locked :class:`~app.models.grade.Grade` on
      :class:`~app.models.essay.EssayVersion` with ``version_number = 1``
      (original submission), AND
    - A locked grade on an EssayVersion with ``version_number >= 2``
      (resubmission).

    When multiple resubmissions exist for the same essay, the *best* (highest)
    resubmission score is used to give the student maximum benefit of doubt
    before triggering the non-responder signal.

    Normalised score = ``total_score / max_possible_score``, clamped to [0, 1].

    Tenant isolation:
        All queries join through ``Class.teacher_id``.

    Args:
        db:         Async database session.
        teacher_id: UUID of the authenticated teacher.

    Returns:
        Mapping of ``student_id → [(original_norm, best_resubmission_norm), …]``.
        Only students with at least one resubmission appear in the result.
    """
    rows_result = await db.execute(
        select(
            Essay.student_id,
            Essay.id.label("essay_id"),
            EssayVersion.version_number,
            Grade.total_score,
            Grade.max_possible_score,
        )
        .join(EssayVersion, Grade.essay_version_id == EssayVersion.id)
        .join(Essay, EssayVersion.essay_id == Essay.id)
        .join(Assignment, Essay.assignment_id == Assignment.id)
        .join(Class, Assignment.class_id == Class.id)
        .where(
            Class.teacher_id == teacher_id,
            Grade.is_locked.is_(True),
            Essay.student_id.is_not(None),
        )
        .order_by(Essay.student_id, Essay.id, EssayVersion.version_number)
    )
    raw_rows = rows_result.all()

    # Group by (student_id, essay_id) → {version_number: normalised_score}.
    student_essay_versions: dict[uuid.UUID, dict[uuid.UUID, dict[int, float]]] = defaultdict(
        lambda: defaultdict(dict)
    )
    for row in raw_rows:
        student_id = cast(uuid.UUID, row.student_id)
        essay_id = cast(uuid.UUID, row.essay_id)
        version_number = int(row.version_number)
        max_possible = float(row.max_possible_score)
        if max_possible > 0:
            norm_score = max(0.0, min(1.0, float(row.total_score) / max_possible))
        else:
            norm_score = 0.0
        student_essay_versions[student_id][essay_id][version_number] = norm_score

    # Extract pairs where both v1 and at least one v2+ exist.
    pairs_by_student: dict[uuid.UUID, list[tuple[float, float]]] = {}
    for student_id, essay_map in student_essay_versions.items():
        pairs: list[tuple[float, float]] = []
        for _essay_id, version_scores in essay_map.items():
            if 1 not in version_scores:
                continue
            resubmission_scores = [s for v, s in version_scores.items() if v >= 2]
            if not resubmission_scores:
                continue
            original_norm = version_scores[1]
            # Use the best resubmission score to give maximum benefit of doubt.
            best_resubmission = max(resubmission_scores)
            pairs.append((original_norm, best_resubmission))
        if pairs:
            pairs_by_student[student_id] = pairs
    return pairs_by_student


# ---------------------------------------------------------------------------
# Public service functions
# ---------------------------------------------------------------------------


async def generate_teacher_worklist(
    db: AsyncSession,
    teacher_id: uuid.UUID,
) -> list[_WorklistItemData]:
    """Compute and return the ranked worklist for a teacher (read-only).

    Loads all student skill profiles, persistent group memberships,
    per-assignment score sequences, and resubmission pairs for the teacher
    in sequential queries, then applies the four trigger checks to each student
    and returns a deterministically ranked list.

    No database writes are performed.  Call :func:`compute_and_persist_worklist`
    to also persist the result.

    Tenant isolation:
        All queries include ``teacher_id``.  No student PII appears in logs.

    Args:
        db:         Async database session.
        teacher_id: UUID of the authenticated teacher.

    Returns:
        Ranked list of :class:`_WorklistItemData` items, most urgent first.
        Returns an empty list if the teacher has no students with profiles.
    """
    profiles = await _load_skill_profiles(db, teacher_id)
    persistent_memberships = await _load_persistent_group_memberships(db, teacher_id)
    per_assignment_scores = await _load_per_assignment_skill_scores_for_all_students(
        db, teacher_id
    )
    resubmission_pairs = await _load_resubmission_pairs_for_all_students(db, teacher_id)

    all_items: list[_WorklistItemData] = []
    for profile in profiles:
        student_id = profile.student_id
        persistent_skills = persistent_memberships.get(student_id, set())
        student_per_asgn = per_assignment_scores.get(student_id, {})
        student_resub_pairs = resubmission_pairs.get(student_id, [])

        all_items.extend(_check_regression(profile))
        all_items.extend(_check_persistent_gap(profile, persistent_skills))
        all_items.extend(_check_high_inconsistency(student_id, student_per_asgn))
        all_items.extend(_check_non_responder(student_id, student_resub_pairs))

    ranked = _rank_items(all_items)

    logger.info(
        "Worklist generated",
        extra={
            "teacher_id": str(teacher_id),
            "item_count": len(ranked),
            "profile_count": len(profiles),
        },
    )
    return ranked


async def compute_and_persist_worklist(
    db: AsyncSession,
    teacher_id: uuid.UUID,
) -> list[TeacherWorklistItem]:
    """Compute the worklist and atomically replace all active items in the DB.

    Generates the ranked worklist via :func:`generate_teacher_worklist`, then
    within a single transaction:

    1. Acquires a ``SELECT … FOR UPDATE`` row lock on the ``users`` row for
       this teacher to serialise concurrent invocations (e.g. two Celery
       tasks triggered by rapid grade locks).  Without this lock both tasks
       would DELETE before either INSERT commits, leaving duplicated
       ``active`` rows after both transactions commit.
    2. Deletes all existing ``active`` items for the teacher (preserving
       ``snoozed``, ``completed``, and ``dismissed`` items for audit purposes
       and so that lifecycle transitions survive a recomputation).
    3. Inserts the freshly computed items with ``status='active'``.

    Idempotency: Running this function twice with the same DB state produces
    the same set of active items (item UUIDs differ between runs, which is
    acceptable — callers must not cache item IDs across recomputations).

    Tenant isolation:
        The DELETE and INSERT are both scoped to ``teacher_id`` so concurrent
        tasks for different teachers do not interfere.

    Args:
        db:         Async database session.
        teacher_id: UUID of the authenticated teacher.

    Returns:
        The newly persisted :class:`TeacherWorklistItem` ORM rows, ordered by
        urgency descending.
    """
    # Capture the generation timestamp before the computation so all items
    # carry a timestamp that reflects when the worklist run was initiated,
    # not when the INSERT executes (which may be seconds later for large
    # teacher rosters).  The same value is reused for created_at so both
    # columns are identical and unambiguous.
    generated_at = datetime.now(UTC)
    computed_items = await generate_teacher_worklist(db, teacher_id)

    # Acquire a row-level lock on the users row to serialise concurrent
    # refresh tasks for the same teacher.  Without this lock, two tasks
    # triggered by rapid grade locks can both DELETE before either INSERT
    # commits, causing both to INSERT the full item set and leaving
    # duplicated active rows.  The lock is released at transaction commit.
    await db.execute(
        select(User.id).where(User.id == teacher_id).with_for_update()
    )

    # Delete all currently active items for this teacher.
    # Non-active items (snoozed, completed, dismissed) are preserved.
    await db.execute(
        delete(TeacherWorklistItem).where(
            TeacherWorklistItem.teacher_id == teacher_id,
            TeacherWorklistItem.status == "active",
        )
    )

    if not computed_items:
        await db.commit()
        logger.info(
            "Worklist persisted — no active items",
            extra={"teacher_id": str(teacher_id)},
        )
        return []

    rows = [
        {
            "id": uuid.uuid4(),
            "teacher_id": teacher_id,
            "student_id": item.student_id,
            "trigger_type": item.trigger_type,
            "skill_key": item.skill_key,
            "urgency": item.urgency,
            "suggested_action": item.suggested_action,
            "details": item.details,
            "status": "active",
            "snoozed_until": None,
            "completed_at": None,
            "generated_at": generated_at,
            "created_at": generated_at,
        }
        for item in computed_items
    ]

    await db.execute(insert(TeacherWorklistItem), rows)
    await db.commit()

    # Reload inserted rows with the same deterministic ordering as _rank_items:
    # urgency desc → trigger_type order → skill_key (NULLs first, then alpha) → student_id.
    result = await db.execute(
        select(TeacherWorklistItem)
        .where(
            TeacherWorklistItem.teacher_id == teacher_id,
            TeacherWorklistItem.status == "active",
            TeacherWorklistItem.generated_at == generated_at,
        )
        .order_by(
            TeacherWorklistItem.urgency.desc(),
            _trigger_order_case_expr(),
            nulls_first(TeacherWorklistItem.skill_key.asc()),
            TeacherWorklistItem.student_id.asc(),
        )
    )
    persisted = list(result.scalars().all())

    logger.info(
        "Worklist persisted",
        extra={
            "teacher_id": str(teacher_id),
            "item_count": len(persisted),
        },
    )
    return persisted


# ---------------------------------------------------------------------------
# Worklist item management (M6-05 — API actions)
# ---------------------------------------------------------------------------

#: Default snooze duration when no ``snoozed_until`` is provided.
_DEFAULT_SNOOZE_DAYS: int = 7


async def get_worklist_for_teacher(
    db: AsyncSession,
    teacher_id: uuid.UUID,
) -> list[TeacherWorklistItem]:
    """Return the ranked active (and currently-active snoozed) worklist items.

    Returns ``active`` items and ``snoozed`` items whose ``snoozed_until`` is in
    the past (i.e. have been un-snoozed by the passage of time).  Items with
    ``status`` of ``'completed'`` or ``'dismissed'`` are excluded.

    Items are ordered identically to :func:`compute_and_persist_worklist`:
    urgency descending, then trigger type, then skill_key, then student_id.

    Tenant isolation: query is scoped to ``teacher_id``.

    Args:
        db:         Async database session.
        teacher_id: UUID of the authenticated teacher.

    Returns:
        Ordered list of :class:`TeacherWorklistItem` ORM rows.
    """
    now = datetime.now(UTC)
    result = await db.execute(
        select(TeacherWorklistItem)
        .where(
            TeacherWorklistItem.teacher_id == teacher_id,
            TeacherWorklistItem.status.in_(["active", "snoozed"]),
            # Include active items unconditionally, and snoozed items only when
            # their snooze window has elapsed.  Treat NULL snoozed_until as
            # expired (e.g. data integrity gap) so the item is never hidden
            # forever.
            (
                (TeacherWorklistItem.status == "active")
                | (
                    (TeacherWorklistItem.status == "snoozed")
                    & (
                        TeacherWorklistItem.snoozed_until.is_(None)
                        | (TeacherWorklistItem.snoozed_until <= now)
                    )
                )
            ),
        )
        .order_by(
            TeacherWorklistItem.urgency.desc(),
            _trigger_order_case_expr(),
            nulls_first(TeacherWorklistItem.skill_key.asc()),
            TeacherWorklistItem.student_id.asc(),
        )
    )
    items = list(result.scalars().all())
    logger.info(
        "Worklist fetched",
        extra={"teacher_id": str(teacher_id), "item_count": len(items)},
    )
    return items


async def _load_worklist_item(
    db: AsyncSession,
    item_id: uuid.UUID,
    teacher_id: uuid.UUID,
) -> TeacherWorklistItem:
    """Load a single worklist item, enforcing tenant isolation.

    Uses a two-step query: step 1 checks existence and ownership via a
    lightweight ``SELECT id, teacher_id WHERE id = ?``; step 2 fetches the full
    row with both ``id`` and ``teacher_id`` filters.

    .. note::
        Under a FORCE RLS policy that filters by ``app.current_teacher_id``,
        step 1 is also subject to RLS, so cross-tenant item IDs may appear as
        non-existent (404) rather than forbidden (403).  This is an acceptable
        design trade-off: revealing that a 404 *might* be a 403 would itself
        leak tenant information.  All mutation endpoints document 404 as the
        possible outcome for both missing and cross-tenant items.

    Args:
        db:         Async database session.
        item_id:    UUID of the worklist item.
        teacher_id: UUID of the authenticated teacher.

    Returns:
        The :class:`TeacherWorklistItem` ORM row.

    Raises:
        :class:`~app.exceptions.NotFoundError`: Item does not exist (or belongs
            to a different teacher under FORCE RLS).
        :class:`~app.exceptions.ForbiddenError`: Item belongs to a different
            teacher (service-layer check; fired when RLS is not active).
    """
    from app.exceptions import ForbiddenError, NotFoundError  # noqa: PLC0415

    # Step 1: lightweight existence + ownership check (distinguishes 404 vs 403
    # even when RLS filters rows by teacher_id at the DB level).
    ownership_result = await db.execute(
        select(TeacherWorklistItem.id, TeacherWorklistItem.teacher_id).where(
            TeacherWorklistItem.id == item_id
        )
    )
    ownership_row = ownership_result.one_or_none()
    if ownership_row is None:
        raise NotFoundError(f"Worklist item {item_id} not found.")
    if ownership_row.teacher_id != teacher_id:
        raise ForbiddenError("You do not have access to this worklist item.")

    # Step 2: fetch full row with both filters to satisfy the tenant-isolation
    # requirement that every DB fetch includes teacher_id in the query itself.
    result = await db.execute(
        select(TeacherWorklistItem).where(
            TeacherWorklistItem.id == item_id,
            TeacherWorklistItem.teacher_id == teacher_id,
        )
    )
    item = result.scalar_one()
    return item


async def complete_worklist_item(
    db: AsyncSession,
    item_id: uuid.UUID,
    teacher_id: uuid.UUID,
) -> TeacherWorklistItem:
    """Mark a worklist item as completed.

    Sets ``status='completed'`` and ``completed_at=now()``.  Idempotent: if the
    item is already ``'completed'`` it is returned unchanged.

    Only ``active`` and ``snoozed`` items may be completed.  Attempting to
    complete a ``dismissed`` item raises
    :class:`~app.exceptions.InvalidStateTransitionError`.

    Tenant isolation: ``teacher_id`` is checked against the item's owner.

    Args:
        db:         Async database session.
        item_id:    UUID of the worklist item.
        teacher_id: UUID of the authenticated teacher.

    Returns:
        Updated :class:`TeacherWorklistItem` ORM row.

    Raises:
        :class:`~app.exceptions.NotFoundError`:  Item does not exist.
        :class:`~app.exceptions.ForbiddenError`: Item belongs to a different teacher.
        :class:`~app.exceptions.InvalidStateTransitionError`: Item is in a
            terminal state (``dismissed``) that cannot transition to
            ``completed``.
    """
    from app.exceptions import InvalidStateTransitionError  # noqa: PLC0415

    item = await _load_worklist_item(db, item_id, teacher_id)
    if item.status == "dismissed":
        raise InvalidStateTransitionError(
            f"Cannot complete a dismissed worklist item (id={item_id})."
        )
    if item.status != "completed":
        now = datetime.now(UTC)
        await db.execute(
            update(TeacherWorklistItem)
            .where(
                TeacherWorklistItem.id == item_id,
                TeacherWorklistItem.teacher_id == teacher_id,
            )
            .values(status="completed", completed_at=now)
        )
        await db.commit()
        await db.refresh(item)
    logger.info(
        "Worklist item completed",
        extra={"item_id": str(item_id), "teacher_id": str(teacher_id)},
    )
    return item


async def snooze_worklist_item(
    db: AsyncSession,
    item_id: uuid.UUID,
    teacher_id: uuid.UUID,
    snoozed_until: datetime | None = None,
) -> TeacherWorklistItem:
    """Snooze a worklist item until a specified datetime.

    Sets ``status='snoozed'`` and persists ``snoozed_until``.  When
    ``snoozed_until`` is ``None``, defaults to
    :data:`_DEFAULT_SNOOZE_DAYS` days from now.

    Only ``active`` and ``snoozed`` items may be snoozed.  Attempting to snooze
    a ``completed`` or ``dismissed`` item raises
    :class:`~app.exceptions.InvalidStateTransitionError`.

    Tenant isolation: ``teacher_id`` is checked against the item's owner.

    Args:
        db:           Async database session.
        item_id:      UUID of the worklist item.
        teacher_id:   UUID of the authenticated teacher.
        snoozed_until: Datetime until which the item should be hidden.
                       Defaults to 7 days from now.

    Returns:
        Updated :class:`TeacherWorklistItem` ORM row.

    Raises:
        :class:`~app.exceptions.NotFoundError`:  Item does not exist.
        :class:`~app.exceptions.ForbiddenError`: Item belongs to a different teacher.
        :class:`~app.exceptions.InvalidStateTransitionError`: Item is in a
            terminal state (``completed`` or ``dismissed``) that cannot be
            snoozed.
    """
    from app.exceptions import InvalidStateTransitionError  # noqa: PLC0415

    item = await _load_worklist_item(db, item_id, teacher_id)
    if item.status in ("completed", "dismissed"):
        raise InvalidStateTransitionError(
            f"Cannot snooze a {item.status} worklist item (id={item_id})."
        )
    if snoozed_until is None:
        snoozed_until = datetime.now(UTC) + timedelta(days=_DEFAULT_SNOOZE_DAYS)
    await db.execute(
        update(TeacherWorklistItem)
        .where(
            TeacherWorklistItem.id == item_id,
            TeacherWorklistItem.teacher_id == teacher_id,
        )
        .values(status="snoozed", snoozed_until=snoozed_until)
    )
    await db.commit()
    await db.refresh(item)
    logger.info(
        "Worklist item snoozed",
        extra={"item_id": str(item_id), "teacher_id": str(teacher_id)},
    )
    return item


async def dismiss_worklist_item(
    db: AsyncSession,
    item_id: uuid.UUID,
    teacher_id: uuid.UUID,
) -> TeacherWorklistItem:
    """Dismiss a worklist item permanently.

    Sets ``status='dismissed'``.  Idempotent: already-dismissed items are
    returned unchanged.

    Only ``active`` and ``snoozed`` items may be dismissed.  Attempting to
    dismiss a ``completed`` item raises
    :class:`~app.exceptions.InvalidStateTransitionError`.

    Tenant isolation: ``teacher_id`` is checked against the item's owner.

    Args:
        db:         Async database session.
        item_id:    UUID of the worklist item.
        teacher_id: UUID of the authenticated teacher.

    Returns:
        Updated :class:`TeacherWorklistItem` ORM row.

    Raises:
        :class:`~app.exceptions.NotFoundError`:  Item does not exist.
        :class:`~app.exceptions.ForbiddenError`: Item belongs to a different teacher.
        :class:`~app.exceptions.InvalidStateTransitionError`: Item is in a
            terminal state (``completed``) that cannot be dismissed.
    """
    from app.exceptions import InvalidStateTransitionError  # noqa: PLC0415

    item = await _load_worklist_item(db, item_id, teacher_id)
    if item.status == "completed":
        raise InvalidStateTransitionError(
            f"Cannot dismiss a completed worklist item (id={item_id})."
        )
    if item.status != "dismissed":
        await db.execute(
            update(TeacherWorklistItem)
            .where(
                TeacherWorklistItem.id == item_id,
                TeacherWorklistItem.teacher_id == teacher_id,
            )
            .values(status="dismissed")
        )
        await db.commit()
        await db.refresh(item)
    logger.info(
        "Worklist item dismissed",
        extra={"item_id": str(item_id), "teacher_id": str(teacher_id)},
    )
    return item
