"""Pydantic schemas for the contact inquiry endpoint.

These schemas are used by the router for request validation and response
serialisation.  They are deliberately minimal — no student PII is collected.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator


class ContactInquiryRequest(BaseModel):
    """Payload for POST /api/v1/contact/inquiry."""

    name: str = Field(..., min_length=1, max_length=200)
    email: EmailStr
    school_name: str = Field(..., min_length=1, max_length=300)
    district: str | None = Field(default=None, max_length=300)
    estimated_teachers: int | None = Field(default=None, ge=1, le=100_000)
    message: str | None = Field(default=None, max_length=5000)

    @field_validator("name", "school_name", mode="before")
    @classmethod
    def strip_whitespace(cls, v: object) -> object:
        if isinstance(v, str):
            return v.strip()
        return v


class ContactInquiryResponse(BaseModel):
    """Response body returned after a successful inquiry submission."""

    id: uuid.UUID
    created_at: datetime

    model_config = {"from_attributes": True}
