"""Assignments router — assignment CRUD endpoints.

All endpoints require a valid JWT (``get_current_teacher`` dependency).
No student PII is collected or processed here.

Endpoints:
  GET    /assignments/{assignmentId}   — get assignment detail
  PATCH  /assignments/{assignmentId}   — update title, prompt, due_date, status
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.db.session import AsyncSession, get_db
from app.dependencies import get_current_teacher
from app.models.assignment import Assignment
from app.models.user import User
from app.schemas.assignment import AssignmentResponse, PatchAssignmentRequest
from app.services.assignment import get_assignment, update_assignment

router = APIRouter(prefix="/assignments", tags=["assignments"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _assignment_response(assignment: Assignment) -> AssignmentResponse:
    """Build an AssignmentResponse from an Assignment ORM instance."""
    return AssignmentResponse.model_validate(assignment)


# ---------------------------------------------------------------------------
# GET /assignments/{assignmentId}
# ---------------------------------------------------------------------------


@router.get(
    "/{assignment_id}",
    summary="Get assignment detail",
)
async def get_assignment_endpoint(
    assignment_id: uuid.UUID,
    teacher: User = Depends(get_current_teacher),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Return a single assignment.

    Returns 404 if the assignment does not exist.
    Returns 403 if the assignment belongs to a different teacher.
    """
    assignment = await get_assignment(db, teacher.id, assignment_id)
    return JSONResponse(
        status_code=200,
        content={"data": _assignment_response(assignment).model_dump(mode="json")},
    )


# ---------------------------------------------------------------------------
# PATCH /assignments/{assignmentId}
# ---------------------------------------------------------------------------


@router.patch(
    "/{assignment_id}",
    summary="Update assignment metadata or advance status",
)
async def patch_assignment_endpoint(
    assignment_id: uuid.UUID,
    payload: PatchAssignmentRequest,
    teacher: User = Depends(get_current_teacher),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Partially update an assignment.

    - ``title``: update the assignment title.
    - ``prompt``: update or clear the assignment prompt.
    - ``due_date``: update or clear the due date.
    - ``status``: advance the assignment through the state machine.
      Valid transitions: draft → open → grading → review → complete → returned.
      Invalid transitions return 422.

    Returns 403 if the assignment belongs to a different teacher.
    Returns 404 if the assignment does not exist.
    Returns 422 if the status transition is not allowed.
    """
    fields_set = payload.model_fields_set
    assignment = await update_assignment(
        db,
        teacher_id=teacher.id,
        assignment_id=assignment_id,
        title=payload.title if "title" in fields_set else None,
        prompt=payload.prompt if "prompt" in fields_set else None,
        update_prompt="prompt" in fields_set,
        due_date=payload.due_date if "due_date" in fields_set else None,
        update_due_date="due_date" in fields_set,
        status=payload.status if "status" in fields_set else None,
    )
    return JSONResponse(
        status_code=200,
        content={"data": _assignment_response(assignment).model_dump(mode="json")},
    )
