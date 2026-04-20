"""Pydantic schemas for the assignment endpoints.

No student PII is collected, processed, or stored here.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field

from app.models.assignment import AssignmentStatus


class CreateAssignmentRequest(BaseModel):
    """Request body for POST /classes/{classId}/assignments."""

    rubric_id: uuid.UUID
    title: str = Field(min_length=1, max_length=255)
    prompt: str | None = None
    due_date: date | None = None


class PatchAssignmentRequest(BaseModel):
    """Request body for PATCH /assignments/{assignmentId}.

    Only fields explicitly included in the request body are updated.
    Use ``model_fields_set`` to determine which fields were provided.

    Note: ``rubric_id`` is intentionally not patchable — the rubric snapshot
    is immutable once an assignment is created.
    """

    title: str | None = Field(default=None, min_length=1, max_length=255)
    prompt: str | None = None
    due_date: date | None = None
    status: AssignmentStatus | None = None


class AssignmentResponse(BaseModel):
    """Full assignment response."""

    id: uuid.UUID
    class_id: uuid.UUID
    rubric_id: uuid.UUID
    rubric_snapshot: dict[str, Any]
    title: str
    prompt: str | None
    due_date: date | None
    status: AssignmentStatus
    resubmission_enabled: bool
    resubmission_limit: int | None
    created_at: datetime

    model_config = {"from_attributes": True}


class AssignmentListItemResponse(BaseModel):
    """Summary item returned by GET /classes/{classId}/assignments."""

    id: uuid.UUID
    class_id: uuid.UUID
    rubric_id: uuid.UUID
    title: str
    prompt: str | None
    due_date: date | None
    status: AssignmentStatus
    resubmission_enabled: bool
    resubmission_limit: int | None
    created_at: datetime

    model_config = {"from_attributes": True}
