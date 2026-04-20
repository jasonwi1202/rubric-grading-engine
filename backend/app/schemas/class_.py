"""Pydantic schemas for the classes endpoints.

No student PII is collected, processed, or stored here.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class CreateClassRequest(BaseModel):
    """Request body for POST /classes."""

    name: str = Field(min_length=1, max_length=255)
    subject: str = Field(min_length=1, max_length=100)
    grade_level: str = Field(min_length=1, max_length=20)
    academic_year: str = Field(min_length=1, max_length=10)


class PatchClassRequest(BaseModel):
    """Request body for PATCH /classes/{classId}.

    Only fields explicitly included in the request body are updated.
    Use ``model_fields_set`` to determine which fields were provided.
    """

    name: str | None = Field(default=None, min_length=1, max_length=255)
    subject: str | None = Field(default=None, min_length=1, max_length=100)
    grade_level: str | None = Field(default=None, min_length=1, max_length=20)
    academic_year: str | None = Field(default=None, min_length=1, max_length=10)


class ClassResponse(BaseModel):
    """Full class response."""

    id: uuid.UUID
    teacher_id: uuid.UUID
    name: str
    subject: str
    grade_level: str
    academic_year: str
    is_archived: bool
    created_at: datetime

    model_config = {"from_attributes": True}
