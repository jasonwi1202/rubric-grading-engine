"""Pydantic schemas for the comment bank endpoints.

No student PII is collected, processed, or stored here.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class CreateCommentBankEntryRequest(BaseModel):
    """Request body for POST /comment-bank."""

    text: str = Field(min_length=1, max_length=2000)


class CommentBankEntryResponse(BaseModel):
    """A single saved comment in the response."""

    id: uuid.UUID
    text: str
    created_at: datetime

    model_config = {"from_attributes": True}


class CommentBankSuggestionResponse(BaseModel):
    """A suggested comment with its match score (0.0–1.0)."""

    id: uuid.UUID
    text: str
    score: float
    created_at: datetime

    model_config = {"from_attributes": True}
