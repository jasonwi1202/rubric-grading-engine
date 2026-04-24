"""Pydantic schemas for media comment endpoints.

No student PII is collected, processed, or stored here.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


class MediaCommentResponse(BaseModel):
    """Response shape for a single media comment record."""

    id: uuid.UUID
    grade_id: uuid.UUID
    s3_key: str
    duration_seconds: int
    mime_type: str
    created_at: datetime

    model_config = {"from_attributes": True}


class MediaCommentUrlResponse(BaseModel):
    """Response shape for GET /media-comments/{id}/url."""

    url: str
