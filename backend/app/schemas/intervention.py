"""Pydantic schemas for intervention recommendations (M7-01).

No student PII is logged.  Student IDs appear in response bodies only,
never in log lines.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class InterventionTriggerType(StrEnum):
    """Intervention agent signal types.

    Ordered from most to least urgent for documentation purposes.
    The actual urgency is stored as an integer on the recommendation row.
    """

    regression = "regression"
    non_responder = "non_responder"
    persistent_gap = "persistent_gap"


class InterventionStatus(StrEnum):
    """Lifecycle status of an intervention recommendation."""

    pending_review = "pending_review"
    approved = "approved"
    dismissed = "dismissed"


class InterventionRecommendationResponse(BaseModel):
    """A single intervention recommendation surfaced to the teacher.

    Matches the ``InterventionRecommendation`` ORM model.  Students are
    identified by ``student_id``; the caller resolves names from the students
    endpoint.
    """

    id: uuid.UUID
    teacher_id: uuid.UUID
    student_id: uuid.UUID
    trigger_type: InterventionTriggerType
    skill_key: str | None = Field(
        default=None,
        description=(
            "Canonical skill dimension key (e.g. 'evidence').  "
            "NULL for student-level triggers such as 'non_responder'."
        ),
    )
    urgency: int = Field(ge=1, le=4, description="1–4; 4 = most urgent.")
    trigger_reason: str = Field(
        description="Human-readable explanation of why this intervention was triggered."
    )
    evidence_summary: str = Field(
        description="Supporting data that backs the trigger (avg_score, trend, etc.)."
    )
    suggested_action: str
    details: dict[str, Any]
    status: InterventionStatus
    actioned_at: datetime | None = None
    created_at: datetime


class InterventionListResponse(BaseModel):
    """Paginated list of intervention recommendations for a teacher."""

    teacher_id: uuid.UUID
    items: list[InterventionRecommendationResponse]
    total_count: int
