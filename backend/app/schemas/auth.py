"""Pydantic schemas for the auth endpoints.

Used by the router for request validation and response serialisation.
No student PII is collected, processed, or stored here.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator


class SignupRequest(BaseModel):
    """Payload for POST /api/v1/auth/signup."""

    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str = Field(..., min_length=1, max_length=100)
    school_name: str = Field(..., min_length=1, max_length=300)

    @field_validator("first_name", "last_name", "school_name", mode="before")
    @classmethod
    def strip_whitespace(cls, v: object) -> object:
        if isinstance(v, str):
            return v.strip()
        return v

    @field_validator("password")
    @classmethod
    def password_complexity(cls, v: str) -> str:
        """Require at least one letter and one digit."""
        has_letter = any(c.isalpha() for c in v)
        has_digit = any(c.isdigit() for c in v)
        if not (has_letter and has_digit):
            raise ValueError("Password must contain at least one letter and one digit.")
        return v


class SignupResponse(BaseModel):
    """Response body returned after a successful sign-up."""

    id: uuid.UUID
    email: str
    message: str
    created_at: datetime

    model_config = {"from_attributes": True}


class VerifyEmailResponse(BaseModel):
    """Response body returned after successfully verifying an email token."""

    message: str


class ResendVerificationRequest(BaseModel):
    """Payload for POST /api/v1/auth/resend-verification."""

    email: EmailStr
