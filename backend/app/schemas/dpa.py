"""Pydantic schemas for the DPA request endpoint.

These schemas are used by the router for request validation and response
serialisation.  Only school administrator contact info is collected —
no student PII.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator


class DpaRequestCreate(BaseModel):
    """Payload for POST /api/v1/contact/dpa-request."""

    name: str = Field(..., min_length=1, max_length=200)
    email: EmailStr
    school_name: str = Field(..., min_length=1, max_length=300)
    district: str | None = Field(default=None, max_length=300)
    message: str | None = Field(default=None, max_length=2000)

    @field_validator("name", "school_name", mode="before")
    @classmethod
    def strip_whitespace(cls, v: object) -> object:
        if isinstance(v, str):
            return v.strip()
        return v


class DpaRequestResponse(BaseModel):
    """Response body returned after a successful DPA request submission."""

    id: uuid.UUID
    created_at: datetime

    model_config = {"from_attributes": True}
