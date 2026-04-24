"""Regrade request service.

Business logic for the regrade request workflow:

- ``create_regrade_request`` — submit a request against a grade; enforces
  the configurable submission window (``REGRADE_WINDOW_DAYS``) and per-grade
  request limit (``REGRADE_MAX_PER_GRADE``).
- ``list_regrade_requests_for_assignment`` — return all requests for every
  grade in an assignment (teacher-only queue view).
- ``resolve_regrade_request`` — approve (with optional new score) or deny
  (requires ``resolution_note``); writes an audit log entry and updates the
  grade if approved.

Security invariants:
- All queries are scoped to the authenticated teacher via the ownership chain
  so cross-teacher access raises ForbiddenError (403).
- No student PII in any log statement — only entity IDs are logged.
- Audit log entries are INSERT-only (no UPDATE or DELETE on audit_logs).
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, cast

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.exceptions import (
    ConflictError,
    ForbiddenError,
    GradeLockedError,
    NotFoundError,
    RegradeRequestLimitReachedError,
    RegradeWindowClosedError,
    ValidationError,
)
from app.models.assignment import Assignment
from app.models.audit_log import AuditLog
from app.models.class_ import Class
from app.models.essay import Essay, EssayVersion
from app.models.grade import CriterionScore, Grade
from app.models.regrade_request import RegradeRequest, RegradeRequestStatus
from app.schemas.regrade_request import (
    RegradeRequestCreate,
    RegradeRequestResolveRequest,
    RegradeRequestResponse,
)

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
        exists_result = await db.execute(select(Grade.id).where(Grade.id == grade_id))
        if exists_result.scalar_one_or_none() is None:
            raise NotFoundError("Grade not found.")
        raise ForbiddenError("You do not have access to this grade.")
    return grade


async def _load_assignment_tenant_scoped(
    db: AsyncSession,
    assignment_id: uuid.UUID,
    teacher_id: uuid.UUID,
) -> Assignment:
    """Load an Assignment record scoped to the authenticated teacher.

    Raises:
        NotFoundError: Assignment does not exist.
        ForbiddenError: Assignment belongs to a different teacher.
    """
    result = await db.execute(
        select(Assignment)
        .join(Class, Assignment.class_id == Class.id)
        .where(
            Assignment.id == assignment_id,
            Class.teacher_id == teacher_id,
        )
    )
    assignment = result.scalar_one_or_none()
    if assignment is None:
        exists_result = await db.execute(
            select(Assignment.id).where(Assignment.id == assignment_id)
        )
        if exists_result.scalar_one_or_none() is None:
            raise NotFoundError("Assignment not found.")
        raise ForbiddenError("You do not have access to this assignment.")
    return assignment


def _build_response(request: RegradeRequest) -> RegradeRequestResponse:
    return RegradeRequestResponse(
        id=request.id,
        grade_id=request.grade_id,
        criterion_score_id=request.criterion_score_id,
        teacher_id=request.teacher_id,
        dispute_text=request.dispute_text,
        status=request.status,
        resolution_note=request.resolution_note,
        resolved_at=request.resolved_at,
        created_at=request.created_at,
    )


# ---------------------------------------------------------------------------
# Public service functions
# ---------------------------------------------------------------------------


async def create_regrade_request(
    db: AsyncSession,
    grade_id: uuid.UUID,
    teacher_id: uuid.UUID,
    body: RegradeRequestCreate,
) -> RegradeRequestResponse:
    """Submit a regrade request against a grade.

    Enforces:
    - Submission window: grade must have been created within the last
      ``REGRADE_WINDOW_DAYS`` days.
    - Per-grade limit: at most ``REGRADE_MAX_PER_GRADE`` open/resolved
      requests are allowed per grade.
    - Criterion ownership: when ``criterion_score_id`` is provided it must
      belong to the given grade.

    Args:
        db: Async database session.
        grade_id: UUID of the Grade being disputed.
        teacher_id: UUID of the authenticated teacher (tenant isolation).
        body: Validated request body.

    Returns:
        A :class:`RegradeRequestResponse` for the newly created request.

    Raises:
        NotFoundError: Grade not found, or criterion_score_id was provided
            but no criterion score exists for this grade.
        ForbiddenError: Grade belongs to a different teacher.
        RegradeWindowClosedError: Submission window has expired.
        RegradeRequestLimitReachedError: Per-grade limit already reached.
    """
    grade = await _load_grade_tenant_scoped(db, grade_id, teacher_id)

    # Enforce submission window.
    window_cutoff = grade.created_at + timedelta(days=settings.regrade_window_days)
    if datetime.now(UTC) > window_cutoff:
        raise RegradeWindowClosedError(
            f"Regrade requests for this grade closed {settings.regrade_window_days} days after grading."
        )

    # Enforce per-grade request limit.
    count_result = await db.execute(
        select(func.count()).select_from(RegradeRequest).where(
            RegradeRequest.grade_id == grade_id
        )
    )
    existing_count = count_result.scalar_one()
    if existing_count >= settings.regrade_max_per_grade:
        raise RegradeRequestLimitReachedError(
            f"This grade already has the maximum number of regrade requests ({settings.regrade_max_per_grade})."
        )

    # Validate criterion_score_id ownership when provided.
    if body.criterion_score_id is not None:
        cs_result = await db.execute(
            select(CriterionScore.id).where(
                CriterionScore.id == body.criterion_score_id,
                CriterionScore.grade_id == grade_id,
            )
        )
        if cs_result.scalar_one_or_none() is None:
            raise NotFoundError("Criterion score not found for this grade.")

    regrade_request = RegradeRequest(
        grade_id=grade_id,
        criterion_score_id=body.criterion_score_id,
        teacher_id=teacher_id,
        dispute_text=body.dispute_text,
        status=RegradeRequestStatus.open,
    )
    db.add(regrade_request)
    await db.commit()
    await db.refresh(regrade_request)

    logger.info(
        "Regrade request created",
        extra={
            "regrade_request_id": str(regrade_request.id),
            "grade_id": str(grade_id),
            "teacher_id": str(teacher_id),
        },
    )
    return _build_response(regrade_request)


async def list_regrade_requests_for_assignment(
    db: AsyncSession,
    assignment_id: uuid.UUID,
    teacher_id: uuid.UUID,
) -> list[RegradeRequestResponse]:
    """Return all regrade requests for every grade in an assignment.

    The queue is ordered by creation timestamp (oldest first) so the teacher
    can work through requests in submission order.

    Args:
        db: Async database session.
        assignment_id: UUID of the Assignment whose requests to list.
        teacher_id: UUID of the authenticated teacher (tenant isolation).

    Returns:
        List of :class:`RegradeRequestResponse` in ascending creation order.

    Raises:
        NotFoundError: Assignment not found.
        ForbiddenError: Assignment belongs to a different teacher.
    """
    await _load_assignment_tenant_scoped(db, assignment_id, teacher_id)

    result = await db.execute(
        select(RegradeRequest)
        .join(Grade, RegradeRequest.grade_id == Grade.id)
        .join(EssayVersion, Grade.essay_version_id == EssayVersion.id)
        .join(Essay, EssayVersion.essay_id == Essay.id)
        .where(Essay.assignment_id == assignment_id)
        .order_by(RegradeRequest.created_at)
    )
    requests = list(result.scalars().all())

    logger.debug(
        "Regrade requests listed for assignment",
        extra={"assignment_id": str(assignment_id), "teacher_id": str(teacher_id)},
    )
    return [_build_response(r) for r in requests]


async def resolve_regrade_request(
    db: AsyncSession,
    request_id: uuid.UUID,
    teacher_id: uuid.UUID,
    body: RegradeRequestResolveRequest,
) -> RegradeRequestResponse:
    """Approve or deny a regrade request.

    - Denied resolutions require a ``resolution_note``.
    - Approved resolutions may optionally set a ``new_criterion_score`` which
      is applied to the targeted CriterionScore (and recalculates the grade's
      ``total_score``).  The score is validated against the rubric snapshot
      min/max bounds and requires the grade to be unlocked.
    - Always writes a ``regrade_resolved`` audit log entry with before/after
      status values.  When a new score is applied, a ``score_override`` audit
      entry is also written for the criterion score.

    Args:
        db: Async database session.
        request_id: UUID of the RegradeRequest to resolve.
        teacher_id: UUID of the authenticated teacher (tenant isolation).
        body: Validated resolution request body.

    Returns:
        Updated :class:`RegradeRequestResponse`.

    Raises:
        NotFoundError: Request not found, or new_criterion_score provided but
            the referenced CriterionScore no longer exists.
        ForbiddenError: Request belongs to a different teacher.
        ValidationError: deny without resolution_note, or new_criterion_score
            provided without a targeted criterion, or score out of rubric range.
        ConflictError: Request is already resolved (not open).
        GradeLockedError: Grade is locked; criterion score cannot be updated.
    """
    # Load the request, enforcing tenant isolation via the grade ownership chain.
    rr_result = await db.execute(
        select(RegradeRequest)
        .join(Grade, RegradeRequest.grade_id == Grade.id)
        .join(EssayVersion, Grade.essay_version_id == EssayVersion.id)
        .join(Essay, EssayVersion.essay_id == Essay.id)
        .join(Assignment, Essay.assignment_id == Assignment.id)
        .join(Class, Assignment.class_id == Class.id)
        .where(
            RegradeRequest.id == request_id,
            Class.teacher_id == teacher_id,
        )
    )
    regrade_request = rr_result.scalar_one_or_none()
    if regrade_request is None:
        exists_result = await db.execute(
            select(RegradeRequest.id).where(RegradeRequest.id == request_id)
        )
        if exists_result.scalar_one_or_none() is None:
            raise NotFoundError("Regrade request not found.")
        raise ForbiddenError("You do not have access to this regrade request.")

    # Guard: only open requests can be resolved.
    if regrade_request.status != RegradeRequestStatus.open:
        raise ConflictError("This regrade request has already been resolved.")

    # Enforce: deny requires a resolution note.
    if body.resolution == "denied" and not body.resolution_note:
        raise ValidationError(
            "A resolution_note is required when denying a regrade request.",
            field="resolution_note",
        )

    # Enforce: new_criterion_score only valid when targeting a criterion.
    if body.new_criterion_score is not None and regrade_request.criterion_score_id is None:
        raise ValidationError(
            "new_criterion_score can only be set when the request targets a specific criterion.",
            field="new_criterion_score",
        )

    before_status = regrade_request.status.value

    # Apply new criterion score when approving a criterion-level request.
    if body.resolution == "approved" and body.new_criterion_score is not None:
        cs_result = await db.execute(
            select(CriterionScore).where(
                CriterionScore.id == regrade_request.criterion_score_id,
                CriterionScore.grade_id == regrade_request.grade_id,
            )
        )
        criterion_score = cs_result.scalar_one_or_none()
        if criterion_score is None:
            raise NotFoundError("Criterion score not found.")

        # Reject edits on locked grades (mirrors override_criterion invariant).
        grade_result = await db.execute(
            select(Grade).where(Grade.id == regrade_request.grade_id)
        )
        grade = grade_result.scalar_one_or_none()
        if grade is not None and grade.is_locked:
            raise GradeLockedError("Grade is locked and cannot be edited.")

        # Validate new score against the immutable rubric snapshot.
        if grade is not None:
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
                    (
                        c
                        for c in criteria_data
                        if str(c["id"]) == str(criterion_score.rubric_criterion_id)
                    ),
                    None,
                )
                if criterion_data is not None:
                    min_score = int(str(criterion_data["min_score"]))
                    max_score = int(str(criterion_data["max_score"]))
                    if not (min_score <= body.new_criterion_score <= max_score):
                        raise ValidationError(
                            f"new_criterion_score {body.new_criterion_score} is out of range [{min_score}, {max_score}].",
                            field="new_criterion_score",
                        )

        before_cs_value: dict[str, object] = {
            "teacher_score": criterion_score.teacher_score,
            "final_score": criterion_score.final_score,
        }
        criterion_score.teacher_score = body.new_criterion_score
        criterion_score.final_score = body.new_criterion_score

        # Write a score_override audit entry for this criterion change.
        score_audit = AuditLog(
            teacher_id=teacher_id,
            entity_type="criterion_score",
            entity_id=criterion_score.id,
            action="score_override",
            before_value=before_cs_value,
            after_value={
                "teacher_score": body.new_criterion_score,
                "final_score": body.new_criterion_score,
            },
        )
        db.add(score_audit)

        # Recompute grade total_score after the override.
        if grade is not None:
            total_result = await db.execute(
                select(CriterionScore.final_score).where(
                    CriterionScore.grade_id == regrade_request.grade_id
                )
            )
            grade.total_score = Decimal(
                sum(
                    score
                    for score in total_result.scalars().all()
                    if score is not None
                )
            )

    # Resolve the request.
    new_status = (
        RegradeRequestStatus.approved
        if body.resolution == "approved"
        else RegradeRequestStatus.denied
    )
    regrade_request.status = new_status
    regrade_request.resolution_note = body.resolution_note
    regrade_request.resolved_at = datetime.now(UTC)

    audit = AuditLog(
        teacher_id=teacher_id,
        entity_type="grade",
        entity_id=regrade_request.grade_id,
        action="regrade_resolved",
        before_value={"status": before_status},
        after_value={
            "status": new_status.value,
            "resolution_note": body.resolution_note,
            "new_criterion_score": body.new_criterion_score,
            "regrade_request_id": str(regrade_request.id),
            "criterion_score_id": (
                str(regrade_request.criterion_score_id)
                if regrade_request.criterion_score_id is not None
                else None
            ),
        },
    )
    db.add(audit)

    await db.commit()
    await db.refresh(regrade_request)

    logger.info(
        "Regrade request resolved",
        extra={
            "regrade_request_id": str(request_id),
            "teacher_id": str(teacher_id),
            "resolution": body.resolution,
        },
    )
    return _build_response(regrade_request)
