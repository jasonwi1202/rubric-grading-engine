"""Regrade request router.

All endpoints require a valid JWT (``get_current_teacher`` dependency).
No student PII is logged — only entity IDs appear in log output.

Endpoints (``grades_regrade_router``, prefix ``/grades``):
  POST  /grades/{gradeId}/regrade-requests          — submit a regrade request

Endpoints (``assignments_regrade_router``, prefix ``/assignments``):
  GET   /assignments/{assignmentId}/regrade-requests — list all requests for assignment

Endpoints (``regrade_requests_router``, prefix ``/regrade-requests``):
  POST  /regrade-requests/{requestId}/resolve        — approve or deny a request
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.db.session import AsyncSession, get_db
from app.dependencies import get_current_teacher
from app.models.user import User
from app.schemas.regrade_request import RegradeRequestCreate, RegradeRequestResolveRequest
from app.services.regrade_request import (
    create_regrade_request,
    list_regrade_requests_for_assignment,
    resolve_regrade_request,
)

#: Router for grade-scoped regrade request creation.
grades_regrade_router = APIRouter(prefix="/grades", tags=["regrade-requests"])

#: Router for assignment-scoped regrade request listing.
assignments_regrade_router = APIRouter(prefix="/assignments", tags=["regrade-requests"])

#: Router for regrade request resolution.
regrade_requests_router = APIRouter(prefix="/regrade-requests", tags=["regrade-requests"])


# ---------------------------------------------------------------------------
# POST /grades/{gradeId}/regrade-requests
# ---------------------------------------------------------------------------


@grades_regrade_router.post(
    "/{grade_id}/regrade-requests",
    status_code=201,
    summary="Submit a regrade request for a grade",
)
async def create_regrade_request_endpoint(
    grade_id: uuid.UUID,
    body: RegradeRequestCreate,
    teacher: User = Depends(get_current_teacher),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Submit a regrade request disputing an AI-generated grade or criterion score.

    Enforces the configurable submission window (``REGRADE_WINDOW_DAYS``) and
    per-grade request limit (``REGRADE_MAX_PER_GRADE``).

    Response body: ``{"data": RegradeRequestResponse}``

    Returns 403 if the grade belongs to a different teacher.
    Returns 404 if the grade or criterion score does not exist.
    Returns 409 if the submission window has closed or the request limit is reached.
    """
    response = await create_regrade_request(
        db=db,
        grade_id=grade_id,
        teacher_id=teacher.id,
        body=body,
    )
    return JSONResponse(
        status_code=201,
        content={"data": response.model_dump(mode="json")},
    )


# ---------------------------------------------------------------------------
# GET /assignments/{assignmentId}/regrade-requests
# ---------------------------------------------------------------------------


@assignments_regrade_router.get(
    "/{assignment_id}/regrade-requests",
    summary="List all regrade requests for an assignment",
)
async def list_regrade_requests_endpoint(
    assignment_id: uuid.UUID,
    teacher: User = Depends(get_current_teacher),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Return all regrade requests across every grade in an assignment, ordered oldest-first.

    Response body: ``{"data": [RegradeRequestResponse, ...]}``

    Returns 403 if the assignment belongs to a different teacher.
    Returns 404 if the assignment does not exist.
    """
    requests = await list_regrade_requests_for_assignment(
        db=db,
        assignment_id=assignment_id,
        teacher_id=teacher.id,
    )
    return JSONResponse(
        status_code=200,
        content={"data": [r.model_dump(mode="json") for r in requests]},
    )


# ---------------------------------------------------------------------------
# POST /regrade-requests/{requestId}/resolve
# ---------------------------------------------------------------------------


@regrade_requests_router.post(
    "/{request_id}/resolve",
    summary="Approve or deny a regrade request",
)
async def resolve_regrade_request_endpoint(
    request_id: uuid.UUID,
    body: RegradeRequestResolveRequest,
    teacher: User = Depends(get_current_teacher),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Approve or deny a regrade request.

    On approval, an optional ``new_criterion_score`` may be applied to the
    targeted criterion.  Denial requires a ``resolution_note``.

    An audit log entry (``regrade_resolved``) is always written on resolution.

    Response body: ``{"data": RegradeRequestResponse}``

    Returns 403 if the request belongs to a different teacher.
    Returns 404 if the request does not exist.
    Returns 422 if deny is requested without a resolution_note.
    """
    response = await resolve_regrade_request(
        db=db,
        request_id=request_id,
        teacher_id=teacher.id,
        body=body,
    )
    return JSONResponse(
        status_code=200,
        content={"data": response.model_dump(mode="json")},
    )
