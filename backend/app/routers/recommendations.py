"""Recommendations router — standalone instruction recommendation actions (M6-08).

All endpoints require a valid JWT (``get_current_teacher`` dependency).
No student PII is logged — only entity IDs appear in log output.

Endpoints:
  POST /recommendations/{recommendationId}/assign — record teacher-confirmed assignment
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.db.session import AsyncSession, get_db
from app.dependencies import get_current_teacher
from app.models.user import User
from app.schemas.instruction_recommendation import recommendation_response_from_orm
from app.services.instruction_recommendation import assign_recommendation

router = APIRouter(prefix="/recommendations", tags=["recommendations"])


# ---------------------------------------------------------------------------
# POST /recommendations/{recommendationId}/assign
# ---------------------------------------------------------------------------


@router.post(
    "/{recommendation_id}/assign",
    summary="Record explicit teacher-confirmed assignment of an instruction recommendation",
)
async def assign_recommendation_endpoint(
    recommendation_id: uuid.UUID,
    teacher: User = Depends(get_current_teacher),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Record the teacher's explicit confirmation to assign an instruction recommendation.

    Transitions the recommendation status from ``'pending_review'`` to
    ``'accepted'`` and writes an audit log entry.

    Idempotent: if the recommendation is already ``'accepted'``, returns the
    existing state without side effects.

    Returns 200 with the updated recommendation set.
    Returns 404 if the recommendation does not exist or belongs to a different teacher
        (cross-tenant IDs are invisible under FORCE RLS and are indistinguishable
        from nonexistent IDs — both surfaces as 404).
    Returns 409 if the recommendation has been dismissed and cannot be assigned.
    """
    rec = await assign_recommendation(db, teacher.id, recommendation_id)
    return JSONResponse(
        status_code=200,
        content={"data": recommendation_response_from_orm(rec).model_dump(mode="json")},
    )
