"""Pydantic schemas for the auto-grouping API (M6-02).

No student PII is logged.  Student names appear in ``StudentInGroupResponse``
only in the response body, never in log lines.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class StudentInGroupResponse(BaseModel):
    """Minimal student summary embedded in a group response.

    Contains enough information for the teacher to identify a student
    without exposing essay content or raw scores.
    """

    id: uuid.UUID
    full_name: str
    external_id: str | None


class StudentGroupResponse(BaseModel):
    """A single skill-gap group with its student list and stability status.

    Matches the ``StudentGroup`` ORM model.  ``students`` is resolved from
    the ``student_ids`` JSONB array by the service layer.
    """

    id: uuid.UUID
    skill_key: str = Field(description="Canonical skill dimension key, e.g. 'evidence'.")
    label: str = Field(description="Human-readable label derived from skill_key.")
    student_count: int = Field(ge=0)
    students: list[StudentInGroupResponse] = Field(
        description="Students sharing this skill gap, ordered by full_name."
    )
    stability: Literal["new", "persistent", "exited"] = Field(
        description=(
            "'new' — first time this skill group appears for the class. "
            "'persistent' — group existed in the previous computation. "
            "'exited' — previously existed but no longer meets the minimum size threshold."
        )
    )
    computed_at: datetime


class ClassGroupsResponse(BaseModel):
    """Response for GET /classes/{classId}/groups.

    Returns all current skill-gap groups for the class, including any groups
    that recently exited (stability='exited').  Groups are ordered by
    stability ('exited' last) then by label alphabetically.
    """

    class_id: uuid.UUID
    groups: list[StudentGroupResponse]
