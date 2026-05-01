"""Intervention recommendations router (M7-01).

All endpoints require a valid JWT (``get_current_teacher`` dependency).
No student PII is logged — only entity IDs appear in log output.

Endpoints:
  GET    /interventions             — list recommendations (pending by default)
  POST   /interventions/{id}/approve — teacher approves a recommendation
  DELETE /interventions/{id}         — teacher dismisses a recommendation
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from app.db.session import AsyncSession, get_db
from app.dependencies import get_current_teacher
from app.models.intervention_recommendation import InterventionRecommendation
from app.models.user import User
from app.schemas.intervention import (
    InterventionRecommendationResponse,
    InterventionStatus,
    InterventionTriggerType,
)
from app.services.intervention_agent import (
    approve_intervention,
    dismiss_intervention,
    list_interventions,
)

router = APIRouter(prefix="/interventions", tags=["interventions"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _rec_response(rec: InterventionRecommendation) -> InterventionRecommendationResponse:
    """Build an :class:`~app.schemas.intervention.InterventionRecommendationResponse`
    from an ORM row.
    """
    return InterventionRecommendationResponse(
        id=rec.id,
        teacher_id=rec.teacher_id,
        student_id=rec.student_id,
        trigger_type=InterventionTriggerType(rec.trigger_type),
        skill_key=rec.skill_key,
        urgency=rec.urgency,
        trigger_reason=rec.trigger_reason,
        evidence_summary=rec.evidence_summary,
        suggested_action=rec.suggested_action,
        details=rec.details,
        status=InterventionStatus(rec.status),
        actioned_at=rec.actioned_at,
        created_at=rec.created_at,
    )


# ---------------------------------------------------------------------------
# GET /interventions
# ---------------------------------------------------------------------------


@router.get(
    "",
    summary="List intervention recommendations for the authenticated teacher",
)
async def list_interventions_endpoint(
    status: str | None = Query(
        default=None,
        description=(
            "Filter by status.  Omit or pass 'pending_review' for items awaiting "
            "review.  Pass 'approved', 'dismissed', or 'all' to include historical items."
        ),
    ),
    teacher: User = Depends(get_current_teacher),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Return intervention recommendations for the authenticated teacher.

    By default (``status`` omitted or ``status=pending_review``) only items
    awaiting teacher review are returned.  Pass ``status=all`` to include
    approved and dismissed items.  Items are ordered by urgency descending,
    then by creation timestamp descending.

    Response body:
    ``{"data": {"teacher_id": "...", "items": [...], "total_count": N}}``
    """
    recs = await list_interventions(db, teacher_id=teacher.id, status=status)
    item_responses = [_rec_response(r) for r in recs]
    payload = {
        "teacher_id": str(teacher.id),
        "items": [r.model_dump(mode="json") for r in item_responses],
        "total_count": len(item_responses),
    }
    return JSONResponse(status_code=200, content={"data": payload})


# ---------------------------------------------------------------------------
# POST /interventions/{id}/approve
# ---------------------------------------------------------------------------


@router.post(
    "/{rec_id}/approve",
    summary="Approve an intervention recommendation",
)
async def approve_intervention_endpoint(
    rec_id: uuid.UUID,
    teacher: User = Depends(get_current_teacher),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Teacher approves the intervention recommendation.

    Records the teacher's explicit confirmation that this intervention should
    be acted upon.  Sets ``status='approved'`` and records ``actioned_at``.
    Idempotent — approving an already-approved item returns 200 unchanged.

    Response body: ``{"data": InterventionRecommendationResponse}``

    Returns 404 if the recommendation does not exist or is not accessible to
    the authenticated teacher.
    Returns 409 if the recommendation is already dismissed.
    """
    rec = await approve_intervention(db, rec_id=rec_id, teacher_id=teacher.id)
    return JSONResponse(
        status_code=200,
        content={"data": _rec_response(rec).model_dump(mode="json")},
    )


# ---------------------------------------------------------------------------
# DELETE /interventions/{id}
# ---------------------------------------------------------------------------


@router.delete(
    "/{rec_id}",
    summary="Dismiss an intervention recommendation",
)
async def dismiss_intervention_endpoint(
    rec_id: uuid.UUID,
    teacher: User = Depends(get_current_teacher),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Teacher dismisses the intervention recommendation.

    Records the teacher's decision to skip this intervention.  Sets
    ``status='dismissed'`` and records ``actioned_at``.  Idempotent —
    dismissing an already-dismissed item returns 200 unchanged.

    Response body: ``{"data": InterventionRecommendationResponse}``

    Returns 404 if the recommendation does not exist or is not accessible to
    the authenticated teacher.
    Returns 409 if the recommendation is already approved.
    """
    rec = await dismiss_intervention(db, rec_id=rec_id, teacher_id=teacher.id)
    return JSONResponse(
        status_code=200,
        content={"data": _rec_response(rec).model_dump(mode="json")},
    )
