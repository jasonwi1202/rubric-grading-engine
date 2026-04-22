"""Grade service.

Business logic for reading and editing grades:

- ``get_grade_for_essay``     — fetch the current grade with criterion scores.
- ``update_grade_feedback``   — update summary_feedback_edited, write audit log.
- ``override_criterion``      — override teacher_score / teacher_feedback on a
                                CriterionScore, update final_score, write audit log.
- ``lock_grade``              — set is_locked=True, write audit log.

Security invariants:
- All queries are scoped to the authenticated teacher via the Essay → Assignment
  → Class join so cross-teacher access raises ForbiddenError (403).
- No student PII in any log statement — only entity IDs are logged.
- Locked grades reject edits with GradeLockedError (409).
- Audit log entries are INSERT-only (no UPDATE or DELETE on audit_logs).
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import (
    ForbiddenError,
    GradeLockedError,
    NotFoundError,
    ValidationError,
)
from app.models.assignment import Assignment
from app.models.audit_log import AuditLog
from app.models.class_ import Class
from app.models.essay import Essay, EssayVersion
from app.models.grade import CriterionScore, Grade
from app.schemas.grade import CriterionScoreResponse, GradeResponse

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _load_grade_tenant_scoped(
    db: AsyncSession,
    grade_id: uuid.UUID,
    teacher_id: uuid.UUID,
) -> Grade:
    """Load a Grade record, enforcing tenant isolation via the essay ownership chain.

    The join path is:
        Grade → EssayVersion → Essay → Assignment → Class (teacher_id)

    Returns:
        The :class:`Grade` record if found and owned by *teacher_id*.

    Raises:
        NotFoundError: Grade does not exist.
        ForbiddenError: Grade exists but belongs to a different teacher.
    """
    result = await db.execute(
        select(Grade)
        .join(EssayVersion, Grade.essay_version_id == EssayVersion.id)
        .join(Essay, EssayVersion.essay_id == Essay.id)
        .join(Assignment, Essay.assignment_id == Assignment.id)
        .join(Class, Assignment.class_id == Class.id)
        .where(
            Grade.id == grade_id,
            Class.teacher_id == teacher_id,
        )
    )
    grade = result.scalar_one_or_none()
    if grade is None:
        # Distinguish 404 from 403 without leaking the existence of another
        # teacher's data — only check existence after the tenant-scoped query
        # returns nothing.
        exists_result = await db.execute(select(Grade.id).where(Grade.id == grade_id))
        if exists_result.scalar_one_or_none() is None:
            raise NotFoundError("Grade not found.")
        raise ForbiddenError("You do not have access to this grade.")
    return grade


async def _load_criterion_scores(
    db: AsyncSession,
    grade_id: uuid.UUID,
) -> list[CriterionScore]:
    """Return all CriterionScore records for *grade_id*, ordered by creation."""
    result = await db.execute(
        select(CriterionScore)
        .where(CriterionScore.grade_id == grade_id)
        .order_by(CriterionScore.created_at)
    )
    return list(result.scalars().all())


def _build_grade_response(grade: Grade, criterion_scores: list[CriterionScore]) -> GradeResponse:
    """Construct a :class:`GradeResponse` from ORM objects."""
    return GradeResponse(
        id=grade.id,
        essay_version_id=grade.essay_version_id,
        total_score=grade.total_score,
        max_possible_score=grade.max_possible_score,
        summary_feedback=grade.summary_feedback,
        summary_feedback_edited=grade.summary_feedback_edited,
        strictness=grade.strictness,
        ai_model=grade.ai_model,
        prompt_version=grade.prompt_version,
        is_locked=grade.is_locked,
        locked_at=grade.locked_at,
        created_at=grade.created_at,
        criterion_scores=[
            CriterionScoreResponse(
                id=cs.id,
                rubric_criterion_id=cs.rubric_criterion_id,
                ai_score=cs.ai_score,
                teacher_score=cs.teacher_score,
                final_score=cs.final_score,
                ai_justification=cs.ai_justification,
                ai_feedback=cs.ai_feedback,
                teacher_feedback=cs.teacher_feedback,
                confidence=cs.confidence,
                created_at=cs.created_at,
            )
            for cs in criterion_scores
        ],
    )


# ---------------------------------------------------------------------------
# Public service functions
# ---------------------------------------------------------------------------


async def get_grade_for_essay(
    db: AsyncSession,
    essay_id: uuid.UUID,
    teacher_id: uuid.UUID,
) -> GradeResponse:
    """Fetch the current grade for an essay with all criterion scores.

    Loads the most recent Grade for the essay's latest EssayVersion.

    Args:
        db: Async database session.
        essay_id: UUID of the Essay whose grade to fetch.
        teacher_id: UUID of the authenticated teacher (tenant isolation).

    Returns:
        A :class:`GradeResponse` with all criterion scores.

    Raises:
        NotFoundError: Essay or grade not found.
        ForbiddenError: Essay belongs to a different teacher.
    """
    # Load essay scoped to teacher.
    essay_result = await db.execute(
        select(Essay)
        .join(Assignment, Essay.assignment_id == Assignment.id)
        .join(Class, Assignment.class_id == Class.id)
        .where(
            Essay.id == essay_id,
            Class.teacher_id == teacher_id,
        )
    )
    essay = essay_result.scalar_one_or_none()
    if essay is None:
        exists_result = await db.execute(select(Essay.id).where(Essay.id == essay_id))
        if exists_result.scalar_one_or_none() is None:
            raise NotFoundError("Essay not found.")
        raise ForbiddenError("You do not have access to this essay.")

    # Load the latest EssayVersion for this essay.
    version_result = await db.execute(
        select(EssayVersion)
        .where(EssayVersion.essay_id == essay_id)
        .order_by(EssayVersion.version_number.desc())
        .limit(1)
    )
    essay_version = version_result.scalar_one_or_none()
    if essay_version is None:
        raise NotFoundError("No essay version found for this essay.")

    # Load the Grade for this EssayVersion.
    grade_result = await db.execute(select(Grade).where(Grade.essay_version_id == essay_version.id))
    grade = grade_result.scalar_one_or_none()
    if grade is None:
        raise NotFoundError("Grade not found for this essay.")

    criterion_scores = await _load_criterion_scores(db, grade.id)
    return _build_grade_response(grade, criterion_scores)


async def update_grade_feedback(
    db: AsyncSession,
    grade_id: uuid.UUID,
    teacher_id: uuid.UUID,
    summary_feedback: str,
) -> GradeResponse:
    """Update the teacher-edited summary feedback for a grade.

    Writes a ``feedback_edited`` audit log entry with ``before_value`` and
    ``after_value`` containing the previous and new ``summary_feedback`` text.

    Args:
        db: Async database session.
        grade_id: UUID of the Grade to update.
        teacher_id: UUID of the authenticated teacher.
        summary_feedback: New summary feedback text.

    Returns:
        Updated :class:`GradeResponse`.

    Raises:
        NotFoundError: Grade not found.
        ForbiddenError: Grade belongs to a different teacher.
        GradeLockedError: Grade is locked — no edits allowed.
    """
    grade = await _load_grade_tenant_scoped(db, grade_id, teacher_id)

    if grade.is_locked:
        raise GradeLockedError("Grade is locked and cannot be edited.")

    before = (
        grade.summary_feedback_edited
        if grade.summary_feedback_edited is not None
        else grade.summary_feedback
    )
    grade.summary_feedback_edited = summary_feedback

    audit = AuditLog(
        teacher_id=teacher_id,
        entity_type="grade",
        entity_id=grade_id,
        action="feedback_edited",
        before_value={"summary_feedback": before},
        after_value={"summary_feedback": summary_feedback},
    )
    db.add(audit)

    await db.commit()
    await db.refresh(grade)
    logger.info(
        "Grade feedback updated",
        extra={"grade_id": str(grade_id), "teacher_id": str(teacher_id)},
    )

    criterion_scores = await _load_criterion_scores(db, grade.id)
    return _build_grade_response(grade, criterion_scores)


async def override_criterion(
    db: AsyncSession,
    grade_id: uuid.UUID,
    criterion_score_id: uuid.UUID,
    teacher_id: uuid.UUID,
    teacher_score: int | None,
    teacher_feedback: str | None,
) -> GradeResponse:
    """Override a criterion score and/or feedback for a grade.

    Updates ``teacher_score``, ``teacher_feedback``, and recalculates
    ``final_score`` (COALESCE(teacher_score, ai_score)).  Writes a
    ``score_override`` audit log entry with ``before_value`` and
    ``after_value``.

    Args:
        db: Async database session.
        grade_id: UUID of the Grade that owns the criterion score.
        criterion_score_id: UUID of the CriterionScore to override.
        teacher_id: UUID of the authenticated teacher.
        teacher_score: New teacher score; ``None`` to leave unchanged.
        teacher_feedback: New teacher feedback; ``None`` to leave unchanged.

    Returns:
        Updated :class:`GradeResponse`.

    Raises:
        NotFoundError: Grade or criterion score not found.
        ForbiddenError: Grade belongs to a different teacher.
        GradeLockedError: Grade is locked — no edits allowed.
        ValidationError: Neither teacher_score nor teacher_feedback was provided.
    """
    if teacher_score is None and teacher_feedback is None:
        raise ValidationError(
            "At least one of teacher_score or teacher_feedback must be provided.",
            field="teacher_score",
        )

    grade = await _load_grade_tenant_scoped(db, grade_id, teacher_id)

    if grade.is_locked:
        raise GradeLockedError("Grade is locked and cannot be edited.")

    # Load the criterion score — verify it belongs to this grade.
    cs_result = await db.execute(
        select(CriterionScore).where(
            CriterionScore.id == criterion_score_id,
            CriterionScore.grade_id == grade_id,
        )
    )
    criterion_score = cs_result.scalar_one_or_none()
    if criterion_score is None:
        raise NotFoundError("Criterion score not found for this grade.")

    if teacher_score is not None:
        # Validate teacher_score against the rubric_snapshot criterion bounds.
        # Always use the immutable snapshot — never the live rubric rows.
        assignment_result = await db.execute(
            select(Assignment)
            .join(Essay, Essay.assignment_id == Assignment.id)
            .join(EssayVersion, EssayVersion.essay_id == Essay.id)
            .where(EssayVersion.id == grade.essay_version_id)
        )
        assignment = assignment_result.scalar_one_or_none()
        if assignment is not None:
            snapshot = cast(dict[str, Any], assignment.rubric_snapshot)
            criteria_data = cast(list[dict[str, Any]], snapshot.get("criteria", []))
            criterion_data = next(
                (c for c in criteria_data if str(c["id"]) == str(criterion_score.rubric_criterion_id)),
                None,
            )
            if criterion_data is not None:
                min_score = int(str(criterion_data["min_score"]))
                max_score = int(str(criterion_data["max_score"]))
                if not (min_score <= teacher_score <= max_score):
                    raise ValidationError(
                        f"teacher_score {teacher_score} is out of range [{min_score}, {max_score}].",
                        field="teacher_score",
                    )

    before_value: dict[str, object] = {
        "teacher_score": criterion_score.teacher_score,
        "teacher_feedback": criterion_score.teacher_feedback,
        "final_score": criterion_score.final_score,
    }

    if teacher_score is not None:
        criterion_score.teacher_score = teacher_score
        criterion_score.final_score = teacher_score

        # Recompute grade.total_score from all criterion final_scores so that
        # GradeResponse.total_score is never stale after an override.
        total_score_result = await db.execute(
            select(CriterionScore.final_score).where(CriterionScore.grade_id == grade_id)
        )
        grade.total_score = Decimal(
            sum(score for score in total_score_result.scalars().all() if score is not None)
        )

    if teacher_feedback is not None:
        criterion_score.teacher_feedback = teacher_feedback

    after_value: dict[str, object] = {
        "teacher_score": criterion_score.teacher_score,
        "teacher_feedback": criterion_score.teacher_feedback,
        "final_score": criterion_score.final_score,
    }

    audit = AuditLog(
        teacher_id=teacher_id,
        entity_type="criterion_score",
        entity_id=criterion_score_id,
        action="score_override",
        before_value=before_value,
        after_value=after_value,
    )
    db.add(audit)

    await db.commit()
    await db.refresh(grade)
    logger.info(
        "Criterion score overridden",
        extra={
            "grade_id": str(grade_id),
            "criterion_score_id": str(criterion_score_id),
            "teacher_id": str(teacher_id),
        },
    )

    criterion_scores = await _load_criterion_scores(db, grade.id)
    return _build_grade_response(grade, criterion_scores)


async def lock_grade(
    db: AsyncSession,
    grade_id: uuid.UUID,
    teacher_id: uuid.UUID,
) -> GradeResponse:
    """Lock a grade so no further edits are allowed.

    Sets ``is_locked=True`` and ``locked_at`` to the current UTC timestamp.
    Writes a ``grade_locked`` audit log entry.  Locking an already-locked
    grade is idempotent and returns the current grade without error.

    Args:
        db: Async database session.
        grade_id: UUID of the Grade to lock.
        teacher_id: UUID of the authenticated teacher.

    Returns:
        The (now-locked) :class:`GradeResponse`.

    Raises:
        NotFoundError: Grade not found.
        ForbiddenError: Grade belongs to a different teacher.
    """
    grade = await _load_grade_tenant_scoped(db, grade_id, teacher_id)

    # Atomic lock: UPDATE ... WHERE is_locked = FALSE so that only one concurrent
    # request can perform the transition, preventing duplicate audit entries.
    now = datetime.now(UTC)
    update_result = await db.execute(
        update(Grade)
        .where(Grade.id == grade_id, Grade.is_locked.is_(False))
        .values(is_locked=True, locked_at=now)
        .returning(Grade.id)
    )
    lock_performed = update_result.scalar_one_or_none() is not None

    if lock_performed:
        # Keep the in-memory object consistent so the response is correct
        # without needing a second SELECT round-trip.
        grade.is_locked = True
        grade.locked_at = now

        audit = AuditLog(
            teacher_id=teacher_id,
            entity_type="grade",
            entity_id=grade_id,
            action="grade_locked",
            before_value={"is_locked": False},
            after_value={"is_locked": True},
        )
        db.add(audit)

        await db.commit()
        await db.refresh(grade)
        logger.info(
            "Grade locked",
            extra={"grade_id": str(grade_id), "teacher_id": str(teacher_id)},
        )

    criterion_scores = await _load_criterion_scores(db, grade.id)
    return _build_grade_response(grade, criterion_scores)
