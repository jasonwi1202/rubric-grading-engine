"""Pydantic schemas for the regrade request endpoints.

No student PII is collected, processed, or stored in these schemas.
All identifier fields use UUIDs; student names never appear here.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.models.regrade_request import RegradeRequestStatus


class RegradeRequestCreate(BaseModel):
    """Request body for POST /grades/{gradeId}/regrade-requests."""

    dispute_text: str = Field(
        ...,
        min_length=1,
        max_length=5000,
        description="Teacher-entered rationale describing why the grade should be reconsidered.",
    )
    # Targets a specific criterion when set; targets the whole grade otherwise.
    criterion_score_id: uuid.UUID | None = Field(
        default=None,
        description="UUID of the CriterionScore being disputed, or null to dispute the overall grade.",
    )


class RegradeRequestResponse(BaseModel):
    """Response body for regrade request endpoints."""

    id: uuid.UUID
    grade_id: uuid.UUID
    criterion_score_id: uuid.UUID | None
    teacher_id: uuid.UUID
    dispute_text: str
    status: RegradeRequestStatus
    resolution_note: str | None
    resolved_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class RegradeRequestResolveRequest(BaseModel):
    """Request body for POST /regrade-requests/{requestId}/resolve."""

    resolution: Literal["approved", "denied"] = Field(
        ...,
        description="Outcome of the review: 'approved' or 'denied'.",
    )
    resolution_note: str | None = Field(
        default=None,
        max_length=5000,
        description="Written explanation of the decision. Required when resolution is 'denied'.",
    )
    # Only meaningful when resolution='approved' and the request targets a specific criterion.
    new_criterion_score: int | None = Field(
        default=None,
        description="New teacher score to apply when approving a criterion-level request.",
    )
