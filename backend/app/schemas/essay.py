"""Pydantic schemas for essay upload and response.

No student PII is collected, processed, or stored here.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel

from app.models.essay import EssayStatus


class EssayVersionResponse(BaseModel):
    """A single essay version within an essay response."""

    id: uuid.UUID
    version_number: int
    word_count: int
    file_storage_key: str | None
    submitted_at: datetime

    model_config = {"from_attributes": True}


class EssayUploadItemResponse(BaseModel):
    """Response for a single essay after upload ingestion."""

    essay_id: uuid.UUID
    essay_version_id: uuid.UUID
    assignment_id: uuid.UUID
    student_id: uuid.UUID | None
    status: EssayStatus
    word_count: int
    file_storage_key: str | None
    submitted_at: datetime

    model_config = {"from_attributes": True}
