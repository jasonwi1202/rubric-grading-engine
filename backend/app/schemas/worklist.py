"""Pydantic schemas for the teacher worklist (M6-04 / M6-05).

No student PII is logged.  Student IDs appear in response bodies only,
never in log lines.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class TriggerType(StrEnum):
    """Worklist signal types.

    Ordered from most to least urgent for documentation purposes.
    The actual urgency is stored as an integer on the worklist item.
    """

    regression = "regression"
    non_responder = "non_responder"
    persistent_gap = "persistent_gap"
    high_inconsistency = "high_inconsistency"


class WorklistItemStatus(StrEnum):
    """Lifecycle status of a worklist item."""

    active = "active"
    snoozed = "snoozed"
    completed = "completed"
    dismissed = "dismissed"


class WorklistItemResponse(BaseModel):
    """A single ranked item in the teacher's worklist.

    Matches the ``TeacherWorklistItem`` ORM model.  Students are identified
    by ``student_id``; the caller resolves names from the students endpoint.
    """

    id: uuid.UUID
    student_id: uuid.UUID
    trigger_type: TriggerType
    skill_key: str | None = Field(
        default=None,
        description=(
            "Canonical skill dimension key (e.g. 'evidence').  "
            "NULL for student-level triggers such as 'non_responder'."
        ),
    )
    urgency: int = Field(ge=1, le=4, description="1–4; 4 = most urgent.")
    suggested_action: str
    details: dict[str, Any]
    status: WorklistItemStatus
    snoozed_until: datetime | None = None
    completed_at: datetime | None = None
    generated_at: datetime
    created_at: datetime


class TeacherWorklistResponse(BaseModel):
    """Full ranked worklist for a teacher.

    ``items`` is ordered by urgency descending (most urgent first).
    ``total_count`` matches ``len(items)`` before any server-side filtering.
    """

    teacher_id: uuid.UUID
    items: list[WorklistItemResponse]
    total_count: int
    generated_at: datetime
