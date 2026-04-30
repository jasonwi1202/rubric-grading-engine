"""Worklist router — teacher worklist management endpoints (M6-05).

All endpoints require a valid JWT (``get_current_teacher`` dependency).
No student PII is logged — only entity IDs appear in log output.

Endpoints:
  GET    /worklist                     — return ranked active worklist items
  POST   /worklist/{itemId}/complete   — mark item as completed
  POST   /worklist/{itemId}/snooze     — snooze item until a given datetime
  DELETE /worklist/{itemId}            — dismiss item permanently
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Body, Depends
from fastapi.responses import JSONResponse

from app.db.session import AsyncSession, get_db
from app.dependencies import get_current_teacher
from app.models.user import User
from app.models.worklist import TeacherWorklistItem
from app.schemas.worklist import (
    SnoozeWorklistItemRequest,
    TriggerType,
    WorklistItemResponse,
    WorklistItemStatus,
)
from app.services.worklist import (
    complete_worklist_item,
    dismiss_worklist_item,
    get_worklist_for_teacher,
    snooze_worklist_item,
)

router = APIRouter(prefix="/worklist", tags=["worklist"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _item_response(item: TeacherWorklistItem) -> WorklistItemResponse:
    """Build a :class:`~app.schemas.worklist.WorklistItemResponse` from an ORM row."""
    return WorklistItemResponse(
        id=item.id,
        student_id=item.student_id,
        trigger_type=TriggerType(item.trigger_type),
        skill_key=item.skill_key,
        urgency=item.urgency,
        suggested_action=item.suggested_action,
        details=item.details,
        status=WorklistItemStatus(item.status),
        snoozed_until=item.snoozed_until,
        completed_at=item.completed_at,
        generated_at=item.generated_at,
        created_at=item.created_at,
    )


# ---------------------------------------------------------------------------
# GET /worklist
# ---------------------------------------------------------------------------


@router.get(
    "",
    summary="Get the authenticated teacher's prioritized worklist",
)
async def get_worklist_endpoint(
    teacher: User = Depends(get_current_teacher),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Return all active worklist items for the authenticated teacher.

    Items are ordered by urgency descending (most urgent first).  Snoozed
    items whose ``snoozed_until`` timestamp has passed are included in the
    response alongside active items (they still carry ``status='snoozed'``).
    Completed and dismissed items are excluded.

    Response body: ``{"data": {"teacher_id": "...", "items": [...], "total_count": N, "generated_at": "..."}}``
    """
    items = await get_worklist_for_teacher(db, teacher_id=teacher.id)
    item_responses = [_item_response(i) for i in items]
    # Use the most recent generation timestamp across all returned items so
    # the response accurately reflects when the newest batch was computed,
    # regardless of which item sorts first by urgency.
    generated_at: datetime = (
        max(i.generated_at for i in items) if items else datetime.now(UTC)
    )
    payload = {
        "teacher_id": str(teacher.id),
        "items": [r.model_dump(mode="json") for r in item_responses],
        "total_count": len(item_responses),
        "generated_at": generated_at.isoformat(),
    }
    return JSONResponse(status_code=200, content={"data": payload})


# ---------------------------------------------------------------------------
# POST /worklist/{itemId}/complete
# ---------------------------------------------------------------------------


@router.post(
    "/{item_id}/complete",
    summary="Mark a worklist item as completed",
)
async def complete_worklist_item_endpoint(
    item_id: uuid.UUID,
    teacher: User = Depends(get_current_teacher),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Mark the worklist item as done.

    Sets ``status='completed'`` and records ``completed_at``.  Idempotent.

    Response body: ``{"data": WorklistItemResponse}``

    Returns 404 if the item does not exist or is not accessible to the
    authenticated teacher.
    """
    item = await complete_worklist_item(db, item_id=item_id, teacher_id=teacher.id)
    return JSONResponse(
        status_code=200,
        content={"data": _item_response(item).model_dump(mode="json")},
    )


# ---------------------------------------------------------------------------
# POST /worklist/{itemId}/snooze
# ---------------------------------------------------------------------------


@router.post(
    "/{item_id}/snooze",
    summary="Snooze a worklist item",
)
async def snooze_worklist_item_endpoint(
    item_id: uuid.UUID,
    body: SnoozeWorklistItemRequest = Body(default_factory=SnoozeWorklistItemRequest),
    teacher: User = Depends(get_current_teacher),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Snooze the worklist item until ``snoozed_until`` (default: 7 days from now).

    Sets ``status='snoozed'`` and persists the ``snoozed_until`` timestamp so
    the item is hidden from the active worklist until that date passes.

    Response body: ``{"data": WorklistItemResponse}``

    Returns 404 if the item does not exist or is not accessible to the
    authenticated teacher.
    """
    item = await snooze_worklist_item(
        db,
        item_id=item_id,
        teacher_id=teacher.id,
        snoozed_until=body.snoozed_until,
    )
    return JSONResponse(
        status_code=200,
        content={"data": _item_response(item).model_dump(mode="json")},
    )


# ---------------------------------------------------------------------------
# DELETE /worklist/{itemId}
# ---------------------------------------------------------------------------


@router.delete(
    "/{item_id}",
    summary="Dismiss a worklist item permanently",
)
async def dismiss_worklist_item_endpoint(
    item_id: uuid.UUID,
    teacher: User = Depends(get_current_teacher),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Permanently dismiss the worklist item.

    Sets ``status='dismissed'``.  The item will no longer appear in the
    active worklist.  Idempotent.

    Response body: ``{"data": WorklistItemResponse}``

    Returns 404 if the item does not exist or is not accessible to the
    authenticated teacher.
    """
    item = await dismiss_worklist_item(db, item_id=item_id, teacher_id=teacher.id)
    return JSONResponse(
        status_code=200,
        content={"data": _item_response(item).model_dump(mode="json")},
    )
