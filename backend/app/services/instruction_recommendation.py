"""Instruction recommendation service (M6-07/M6-08/M6-09).

Business logic for generating, persisting, and retrieving AI-powered
instruction recommendations from student skill profiles or class skill-gap
groups.

Public API:
  - ``generate_student_recommendations`` — generate recommendations from a
    student's skill profile and persist the validated result.
  - ``generate_group_recommendations``   — generate recommendations targeting
    a class skill-gap group's shared skill gap and persist the result.
  - ``list_student_recommendations``     — return all persisted recommendation
    sets for a student (newest-first).
  - ``assign_recommendation``            — record the teacher's explicit
    confirmation to assign a recommendation (status → 'accepted').
  - ``dismiss_recommendation``           — record the teacher's explicit
    dismissal of a recommendation (status → 'dismissed').

LLM integration:
  - Only aggregate skill profile data is sent to the LLM — no essay content.
  - The :func:`~app.llm.client.call_instruction` function sends a system
    prompt that explicitly instructs the model to ignore directives in the
    profile data (prompt injection defense).
  - LLM responses are parsed and validated against the instruction response
    schema before any DB write; the parser accepts empty recommendation lists
    and blank field values, so callers should not assume non-empty output.
  - The ``prompt_version`` field on each persisted row records which version
    of the instruction prompt was used.

Tenant isolation:
  Every function accepts ``teacher_id`` and includes it in every query.
  For ``assign_recommendation``, cross-tenant access returns 404 (not 403) —
  matching the RLS pattern used by the worklist service.  For generation
  functions, cross-teacher access raises :exc:`~app.exceptions.ForbiddenError`.

FERPA:
  No student PII (names, essay content, raw scores) is written to log
  statements.  Only entity IDs (``student_id``, ``group_id``,
  ``recommendation_id``) appear in log lines.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any, cast

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import ConflictError, ForbiddenError, NotFoundError, ValidationError
from app.llm.client import call_instruction
from app.llm.prompts.instruction_v1 import VERSION as INSTRUCTION_PROMPT_VERSION
from app.models.audit_log import AuditLog
from app.models.instruction_recommendation import InstructionRecommendation
from app.models.student import Student
from app.models.student_group import StudentGroup
from app.models.student_skill_profile import StudentSkillProfile
from app.models.worklist import TeacherWorklistItem

logger = logging.getLogger(__name__)

# Gap threshold: a skill with avg_score below this is considered a gap.
_GAP_THRESHOLD = 0.6


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _assert_student_owned_by(
    db: AsyncSession,
    student_id: uuid.UUID,
    teacher_id: uuid.UUID,
) -> None:
    """Verify that the student exists and belongs to the given teacher.

    Raises:
        NotFoundError:  Student does not exist.
        ForbiddenError: Student belongs to a different teacher.
    """
    result = await db.execute(
        select(Student.id, Student.teacher_id).where(Student.id == student_id)
    )
    row = result.one_or_none()
    if row is None:
        raise NotFoundError("Student not found.")
    if row.teacher_id != teacher_id:
        raise ForbiddenError("You do not have access to this student.")


async def _assert_group_owned_by(
    db: AsyncSession,
    group_id: uuid.UUID,
    teacher_id: uuid.UUID,
) -> StudentGroup:
    """Verify that the group exists and belongs to the given teacher.

    Raises:
        NotFoundError:  Group does not exist.
        ForbiddenError: Group belongs to a different teacher.
    """
    result = await db.execute(select(StudentGroup).where(StudentGroup.id == group_id))
    group = result.scalar_one_or_none()
    if group is None:
        raise NotFoundError("Student group not found.")
    if group.teacher_id != teacher_id:
        raise ForbiddenError("You do not have access to this student group.")
    return group


async def _assert_worklist_item_owned_by(
    db: AsyncSession,
    worklist_item_id: uuid.UUID,
    teacher_id: uuid.UUID,
) -> None:
    """Verify that the worklist item exists and belongs to the given teacher.

    Raises:
        NotFoundError:  Worklist item does not exist.
        ForbiddenError: Worklist item belongs to a different teacher.
    """
    result = await db.execute(
        select(TeacherWorklistItem.id, TeacherWorklistItem.teacher_id).where(
            TeacherWorklistItem.id == worklist_item_id
        )
    )
    row = result.one_or_none()
    if row is None:
        raise NotFoundError("Worklist item not found.")
    if row.teacher_id != teacher_id:
        raise ForbiddenError("You do not have access to this worklist item.")


def _build_evidence_summary(
    skill_scores: dict[str, Any],
    skill_key: str | None,
) -> str:
    """Build a human-readable evidence summary from a skill profile.

    If ``skill_key`` is provided, the summary describes only that skill's
    performance.  Otherwise it lists all identified gap dimensions ordered by
    ascending avg_score.

    Args:
        skill_scores: The ``skill_scores`` JSONB value from
            :class:`~app.models.student_skill_profile.StudentSkillProfile`.
        skill_key: Optional single skill dimension to focus on.

    Returns:
        A short evidence summary string suitable for display to the teacher.
    """
    if skill_key:
        entry = skill_scores.get(skill_key)
        if entry and isinstance(entry, dict):
            avg = entry.get("avg_score", 0.0)
            trend = entry.get("trend", "stable")
            return (
                f"Skill gap detected in '{skill_key}': average score {avg:.0%}, trend is {trend}."
            )
        return f"Skill dimension '{skill_key}' requested but no profile data found."

    gaps = [
        (key, data)
        for key, data in skill_scores.items()
        if isinstance(data, dict) and data.get("avg_score", 1.0) < _GAP_THRESHOLD
    ]
    if not gaps:
        return "No skill gaps detected below the performance threshold."

    gaps.sort(key=lambda kv: kv[1].get("avg_score", 1.0))
    parts = [f"'{key}' ({data.get('avg_score', 0.0):.0%})" for key, data in gaps]
    return f"Skill gaps detected in: {', '.join(parts)}."


def _filter_skill_profile_for_prompt(
    skill_scores: dict[str, Any],
    skill_key: str | None,
) -> dict[str, Any]:
    """Return a subset of the skill profile to send to the LLM.

    If ``skill_key`` is given, include only that dimension.  Otherwise return
    all dimensions with avg_score below the gap threshold, to focus the LLM on
    genuine weaknesses rather than strong areas.

    No essay content or student PII is included — only aggregate performance
    numbers.

    Args:
        skill_scores: The full skill_scores dict from the profile.
        skill_key: Optional skill dimension to restrict to.

    Returns:
        A filtered skill_scores dict suitable for JSON-serialisation and
        inclusion in the instruction prompt.
    """
    if skill_key:
        entry = skill_scores.get(skill_key)
        return {skill_key: entry} if isinstance(entry, dict) else {}

    return {
        key: data
        for key, data in skill_scores.items()
        if isinstance(data, dict) and data.get("avg_score", 1.0) < _GAP_THRESHOLD
    }


# ---------------------------------------------------------------------------
# Public service functions
# ---------------------------------------------------------------------------


async def generate_student_recommendations(
    db: AsyncSession,
    teacher_id: uuid.UUID,
    student_id: uuid.UUID,
    *,
    grade_level: str,
    duration_minutes: int,
    skill_key: str | None = None,
    worklist_item_id: uuid.UUID | None = None,
) -> InstructionRecommendation:
    """Generate and persist instruction recommendations from a student's skill profile.

    Workflow:
    1. Verify student ownership (raises 404/403 on failure).
    2. Load the student's skill profile (raises 404 if none exists).
    3. Optionally verify worklist item ownership.
    4. Build the evidence summary from profile gaps.
    5. Call the LLM with the filtered skill profile (no essay content).
    6. Validate the LLM response (parser raises LLMParseError on failure).
    7. Persist and return the recommendation row.

    Args:
        db:               Async database session.
        teacher_id:       Authenticated teacher's UUID (tenant scope).
        student_id:       Student to generate recommendations for.
        grade_level:      Grade-level descriptor (e.g. ``"Grade 8"``).
        duration_minutes: Target activity duration in minutes.
        skill_key:        Optional single skill dimension to target.
        worklist_item_id: Optional worklist item that triggered this generation.

    Returns:
        The newly created :class:`~app.models.instruction_recommendation.InstructionRecommendation` row.

    Raises:
        NotFoundError:  Student or their skill profile not found.
        ForbiddenError: Student belongs to a different teacher.
        ValidationError: No skill profile data available to generate from.
        LLMParseError:  LLM response could not be parsed after retry.
        LLMError:       LLM service unavailable.
    """
    await _assert_student_owned_by(db, student_id, teacher_id)

    if worklist_item_id is not None:
        await _assert_worklist_item_owned_by(db, worklist_item_id, teacher_id)

    # Load skill profile — both teacher_id and student_id are required as a
    # defense-in-depth measure for tenant isolation: the ownership check above
    # verified the student belongs to this teacher, and the query filter here
    # ensures that even if that check were bypassed (e.g. via a direct DB call),
    # a teacher still cannot retrieve another teacher's profile.
    result = await db.execute(
        select(StudentSkillProfile).where(
            StudentSkillProfile.teacher_id == teacher_id,
            StudentSkillProfile.student_id == student_id,
        )
    )
    profile = result.scalar_one_or_none()
    if profile is None:
        raise NotFoundError(
            "No skill profile found for this student. "
            "Grade at least one assignment to generate a profile."
        )

    skill_scores: dict[str, Any] = profile.skill_scores or {}
    if not skill_scores:
        raise ValidationError(
            "Student skill profile has no data yet. Grade at least one assignment first.",
            field="student_id",
        )

    filtered_scores = _filter_skill_profile_for_prompt(skill_scores, skill_key)
    evidence_summary = _build_evidence_summary(skill_scores, skill_key)
    skill_profile_json = json.dumps(filtered_scores)

    logger.info(
        "Generating instruction recommendations for student",
        extra={"student_id": str(student_id), "teacher_id": str(teacher_id)},
    )

    parsed = await call_instruction(
        skill_profile_json=skill_profile_json,
        grade_level=grade_level,
        duration_minutes=duration_minutes,
    )

    recs_payload = [
        {
            "skill_dimension": r.skill_dimension,
            "title": r.title,
            "description": r.description,
            "estimated_minutes": r.estimated_minutes,
            "strategy_type": r.strategy_type,
        }
        for r in parsed.recommendations
    ]

    recommendation = InstructionRecommendation(
        id=uuid.uuid4(),
        teacher_id=teacher_id,
        student_id=student_id,
        group_id=None,
        worklist_item_id=worklist_item_id,
        skill_key=skill_key,
        grade_level=grade_level,
        prompt_version=INSTRUCTION_PROMPT_VERSION,
        recommendations=recs_payload,
        evidence_summary=evidence_summary,
        status="pending_review",
    )
    db.add(recommendation)
    await db.commit()
    await db.refresh(recommendation)

    logger.info(
        "Instruction recommendations generated and persisted",
        extra={
            "recommendation_id": str(recommendation.id),
            "student_id": str(student_id),
            "teacher_id": str(teacher_id),
        },
    )
    return recommendation


async def generate_group_recommendations(
    db: AsyncSession,
    teacher_id: uuid.UUID,
    class_id: uuid.UUID,
    group_id: uuid.UUID,
    *,
    grade_level: str,
    duration_minutes: int,
) -> InstructionRecommendation:
    """Generate and persist instruction recommendations for a class skill-gap group.

    The group's shared skill gap (``skill_key``) is used as the sole focus.
    A synthetic skill profile is built from the group metadata so no individual
    student PII is sent to the LLM.

    Args:
        db:               Async database session.
        teacher_id:       Authenticated teacher's UUID (tenant scope).
        class_id:         Class that owns the group (used for ownership check).
        group_id:         Skill-gap group to generate recommendations for.
        grade_level:      Grade-level descriptor (e.g. ``"Grade 8"``).
        duration_minutes: Target activity duration in minutes.

    Returns:
        The newly created :class:`~app.models.instruction_recommendation.InstructionRecommendation` row.

    Raises:
        NotFoundError:  Group not found.
        ForbiddenError: Group or class belongs to a different teacher.
        LLMParseError:  LLM response could not be parsed after retry.
        LLMError:       LLM service unavailable.
    """
    group = await _assert_group_owned_by(db, group_id, teacher_id)

    # Verify the group belongs to the class specified in the URL.
    if group.class_id != class_id:
        raise NotFoundError("Student group not found.")

    skill_key = group.skill_key
    student_count = group.student_count

    # Build a synthetic profile to send to the LLM.
    # We use a low placeholder avg_score to signal this is a genuine gap;
    # individual student scores are never included so no PII leaks.
    synthetic_profile: dict[str, Any] = {
        skill_key: {
            "avg_score": 0.4,
            "trend": "stable",
            "data_points": student_count,
            "note": f"{student_count} students share this gap",
        }
    }
    evidence_summary = (
        f"Skill gap group with {student_count} student(s) underperforming "
        f"in '{skill_key}' (stability: {group.stability})."
    )

    logger.info(
        "Generating instruction recommendations for group",
        extra={
            "group_id": str(group_id),
            "class_id": str(class_id),
            "teacher_id": str(teacher_id),
        },
    )

    parsed = await call_instruction(
        skill_profile_json=json.dumps(synthetic_profile),
        grade_level=grade_level,
        duration_minutes=duration_minutes,
    )

    recs_payload = [
        {
            "skill_dimension": r.skill_dimension,
            "title": r.title,
            "description": r.description,
            "estimated_minutes": r.estimated_minutes,
            "strategy_type": r.strategy_type,
        }
        for r in parsed.recommendations
    ]

    recommendation = InstructionRecommendation(
        id=uuid.uuid4(),
        teacher_id=teacher_id,
        student_id=None,
        group_id=group_id,
        worklist_item_id=None,
        skill_key=skill_key,
        grade_level=grade_level,
        prompt_version=INSTRUCTION_PROMPT_VERSION,
        recommendations=recs_payload,
        evidence_summary=evidence_summary,
        status="pending_review",
    )
    db.add(recommendation)
    await db.commit()
    await db.refresh(recommendation)

    logger.info(
        "Instruction recommendations generated and persisted for group",
        extra={
            "recommendation_id": str(recommendation.id),
            "group_id": str(group_id),
            "teacher_id": str(teacher_id),
        },
    )
    return recommendation


async def list_student_recommendations(
    db: AsyncSession,
    teacher_id: uuid.UUID,
    student_id: uuid.UUID,
) -> list[InstructionRecommendation]:
    """Return all persisted recommendation sets for a student, newest-first.

    Both ``teacher_id`` and ``student_id`` are included in the query so a
    teacher cannot read another teacher's recommendations.

    Args:
        db:         Async database session.
        teacher_id: Authenticated teacher's UUID (tenant scope).
        student_id: Student whose recommendations to retrieve.

    Returns:
        List of :class:`~app.models.instruction_recommendation.InstructionRecommendation`
        rows ordered by ``created_at`` descending.

    Raises:
        NotFoundError:  Student not found.
        ForbiddenError: Student belongs to a different teacher.
    """
    await _assert_student_owned_by(db, student_id, teacher_id)

    result = await db.execute(
        select(InstructionRecommendation)
        .where(
            InstructionRecommendation.teacher_id == teacher_id,
            InstructionRecommendation.student_id == student_id,
        )
        .order_by(InstructionRecommendation.created_at.desc())
    )
    return list(result.scalars().all())


async def assign_recommendation(
    db: AsyncSession,
    teacher_id: uuid.UUID,
    recommendation_id: uuid.UUID,
) -> InstructionRecommendation:
    """Record the teacher's explicit confirmation to assign an instruction recommendation.

    Transitions the recommendation status from ``'pending_review'`` to
    ``'accepted'`` and writes an audit log entry.

    Idempotent: if the recommendation is already ``'accepted'``, it is returned
    unchanged without writing a second audit entry.

    Tenant isolation:
        Uses a single ``SELECT … WHERE id = ? AND teacher_id = ?`` query —
        matching the RLS pattern used by :func:`worklist._load_worklist_item`.
        With FORCE RLS enabled, cross-tenant rows are invisible at the DB level,
        so a cross-tenant ID and a nonexistent ID are indistinguishable.  Both
        raise :exc:`~app.exceptions.NotFoundError` (404), which avoids leaking
        whether a resource exists for another teacher.

    Concurrency:
        Uses a conditional ``UPDATE … WHERE status = 'pending_review'`` to
        atomically perform the transition.  If two concurrent requests race,
        only one will see a rowcount of 1 and write the audit entry; the other
        will fall through as idempotent.

    Args:
        db:                Async database session.
        teacher_id:        Authenticated teacher's UUID (tenant scope).
        recommendation_id: Recommendation to assign.

    Returns:
        The updated :class:`~app.models.instruction_recommendation.InstructionRecommendation` row.

    Raises:
        NotFoundError:  Recommendation not found or not accessible to this teacher.
        ConflictError:  Recommendation has been dismissed and cannot be assigned.
    """
    # Single query with teacher_id predicate — RLS-consistent pattern.
    # Cross-tenant and nonexistent IDs both return None → 404.
    result = await db.execute(
        select(InstructionRecommendation).where(
            InstructionRecommendation.id == recommendation_id,
            InstructionRecommendation.teacher_id == teacher_id,
        )
    )
    rec = result.scalar_one_or_none()
    if rec is None:
        raise NotFoundError("Instruction recommendation not found.")

    if rec.status == "dismissed":
        raise ConflictError("Cannot assign a dismissed recommendation.")

    # Idempotent — already accepted, nothing to do.
    if rec.status == "accepted":
        return rec

    # Atomic conditional UPDATE: only transitions if still pending_review.
    # This prevents duplicate audit entries when two concurrent POSTs race.
    before_status = rec.status
    update_result = await db.execute(
        update(InstructionRecommendation)
        .where(
            InstructionRecommendation.id == recommendation_id,
            InstructionRecommendation.teacher_id == teacher_id,
            InstructionRecommendation.status == "pending_review",
        )
        .values(status="accepted")
    )
    if cast("CursorResult[Any]", update_result).rowcount == 0:
        # Concurrent request already transitioned the row; re-fetch current state.
        await db.refresh(rec)
        return rec

    audit = AuditLog(
        teacher_id=teacher_id,
        entity_type="instruction_recommendation",
        entity_id=recommendation_id,
        action="recommendation_assigned",
        before_value={"status": before_status},
        after_value={"status": "accepted"},
    )
    db.add(audit)
    await db.commit()
    await db.refresh(rec)

    logger.info(
        "Instruction recommendation assigned",
        extra={
            "recommendation_id": str(recommendation_id),
            "teacher_id": str(teacher_id),
        },
    )
    return rec


async def dismiss_recommendation(
    db: AsyncSession,
    teacher_id: uuid.UUID,
    recommendation_id: uuid.UUID,
) -> InstructionRecommendation:
    """Record the teacher's explicit dismissal of an instruction recommendation.

    Transitions the recommendation status from ``'pending_review'`` to
    ``'dismissed'`` and writes an audit log entry.

    Idempotent: if the recommendation is already ``'dismissed'``, it is
    returned unchanged without writing a second audit entry.

    Tenant isolation:
        Uses a single ``SELECT … WHERE id = ? AND teacher_id = ?`` query —
        matching the RLS pattern used by :func:`assign_recommendation`.
        Cross-tenant and nonexistent IDs both raise
        :exc:`~app.exceptions.NotFoundError` (404).

    Args:
        db:                Async database session.
        teacher_id:        Authenticated teacher's UUID (tenant scope).
        recommendation_id: Recommendation to dismiss.

    Returns:
        The updated :class:`~app.models.instruction_recommendation.InstructionRecommendation` row.

    Raises:
        NotFoundError:  Recommendation not found or not accessible to this teacher.
        ConflictError:  Recommendation has already been assigned and cannot be dismissed.
    """
    result = await db.execute(
        select(InstructionRecommendation).where(
            InstructionRecommendation.id == recommendation_id,
            InstructionRecommendation.teacher_id == teacher_id,
        )
    )
    rec = result.scalar_one_or_none()
    if rec is None:
        raise NotFoundError("Instruction recommendation not found.")

    if rec.status == "accepted":
        raise ConflictError("Cannot dismiss a recommendation that has already been assigned.")

    # Idempotent — already dismissed, nothing to do.
    if rec.status == "dismissed":
        return rec

    before_status = rec.status
    update_result = await db.execute(
        update(InstructionRecommendation)
        .where(
            InstructionRecommendation.id == recommendation_id,
            InstructionRecommendation.teacher_id == teacher_id,
            InstructionRecommendation.status == "pending_review",
        )
        .values(status="dismissed")
    )
    if cast("CursorResult[Any]", update_result).rowcount == 0:
        await db.refresh(rec)
        return rec

    audit = AuditLog(
        teacher_id=teacher_id,
        entity_type="instruction_recommendation",
        entity_id=recommendation_id,
        action="recommendation_dismissed",
        before_value={"status": before_status},
        after_value={"status": "dismissed"},
    )
    db.add(audit)
    await db.commit()
    await db.refresh(rec)

    logger.info(
        "Instruction recommendation dismissed",
        extra={
            "recommendation_id": str(recommendation_id),
            "teacher_id": str(teacher_id),
        },
    )
    return rec
