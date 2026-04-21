"""Assignments router — assignment CRUD and batch grading endpoints.

All endpoints require a valid JWT (``get_current_teacher`` dependency).
No student PII is collected or logged here.

Endpoints:
  GET    /assignments/{assignmentId}                — get assignment detail
  PATCH  /assignments/{assignmentId}                — update title, prompt, due_date, status
  POST   /assignments/{assignmentId}/grade          — trigger batch grading (returns 202)
  GET    /assignments/{assignmentId}/grading-status — read per-essay progress from Redis
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from redis.asyncio import Redis

from app.db.session import AsyncSession, get_db
from app.dependencies import get_current_teacher
from app.models.assignment import Assignment
from app.models.user import User
from app.schemas.assignment import AssignmentResponse, PatchAssignmentRequest
from app.schemas.batch_grading import (
    GradingStatusResponse,
    TriggerGradingRequest,
    TriggerGradingResponse,
)
from app.services.assignment import get_assignment, update_assignment
from app.services.batch_grading import get_grading_status, trigger_batch_grading

router = APIRouter(prefix="/assignments", tags=["assignments"])


# ---------------------------------------------------------------------------
# Redis dependency — local to this router (same pattern as auth/contact)
# ---------------------------------------------------------------------------


async def _get_redis() -> AsyncGenerator[Redis, None]:  # type: ignore[type-arg]
    """FastAPI dependency that yields an async Redis client."""
    from app.config import settings

    client: Redis = Redis.from_url(settings.redis_url, decode_responses=True)  # type: ignore[type-arg]
    try:
        yield client
    finally:
        await client.aclose()  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _assignment_response(assignment: Assignment) -> AssignmentResponse:
    """Build an AssignmentResponse from an Assignment ORM instance."""
    return AssignmentResponse.model_validate(assignment)


# ---------------------------------------------------------------------------
# POST /assignments/{assignmentId}/grade
# ---------------------------------------------------------------------------


@router.post(
    "/{assignment_id}/grade",
    status_code=202,
    summary="Trigger batch grading for an assignment",
)
async def trigger_grading_endpoint(
    assignment_id: uuid.UUID,
    payload: TriggerGradingRequest,
    teacher: User = Depends(get_current_teacher),
    db: AsyncSession = Depends(get_db),
    redis_client: Redis = Depends(_get_redis),  # type: ignore[type-arg]
) -> JSONResponse:
    """Enqueue one grading task per queued essay and return 202 immediately.

    Does not wait for any task to complete.  Poll
    ``GET /assignments/{id}/grading-status`` for live progress.

    Returns 202 with ``{"data": {"enqueued": N, "assignment_id": "..."}}``
    on success.

    Returns 403 if the assignment belongs to a different teacher.
    Returns 404 if the assignment does not exist.
    Returns 409 if the assignment is not in a gradeable state or has no
    queued essays.
    """
    enqueued = await trigger_batch_grading(
        db=db,
        redis=redis_client,
        assignment_id=assignment_id,
        teacher_id=teacher.id,
        essay_ids=payload.essay_ids,
        strictness=payload.strictness,
    )
    response = TriggerGradingResponse(enqueued=enqueued, assignment_id=assignment_id)
    return JSONResponse(
        status_code=202,
        content={"data": response.model_dump(mode="json")},
    )


# ---------------------------------------------------------------------------
# GET /assignments/{assignmentId}/grading-status
# ---------------------------------------------------------------------------


@router.get(
    "/{assignment_id}/grading-status",
    summary="Get batch grading progress",
)
async def get_grading_status_endpoint(
    assignment_id: uuid.UUID,
    teacher: User = Depends(get_current_teacher),
    db: AsyncSession = Depends(get_db),
    redis_client: Redis = Depends(_get_redis),  # type: ignore[type-arg]
) -> JSONResponse:
    """Return the current batch grading progress for an assignment.

    Reads entirely from Redis after a single ownership check — safe to poll
    every 3 seconds from the frontend without hammering the database.

    Response shape::

        {
          "data": {
            "status": "processing",  // idle|processing|complete|failed|partial
            "total": 30,
            "complete": 12,
            "failed": 1,
            "essays": [
              {"id": "...", "status": "complete", "student_name": "..."},
              {"id": "...", "status": "failed",   "error": "LLM_UNAVAILABLE"}
            ]
          }
        }

    Returns 403 if the assignment belongs to a different teacher.
    Returns 404 if the assignment does not exist.
    """
    status_data = await get_grading_status(
        db=db,
        redis=redis_client,
        assignment_id=assignment_id,
        teacher_id=teacher.id,
    )
    response = GradingStatusResponse.model_validate(status_data)
    return JSONResponse(
        status_code=200,
        content={"data": response.model_dump(mode="json")},
    )


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
