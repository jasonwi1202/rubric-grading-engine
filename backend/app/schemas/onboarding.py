"""Pydantic schemas for the onboarding endpoints.

No student PII is collected, processed, or stored here.
"""

from datetime import datetime

from pydantic import BaseModel


class OnboardingStatusResponse(BaseModel):
    """Response body for GET /api/v1/onboarding/status."""

    step: int
    """The wizard step the teacher should resume at (1 = create class,
    2 = create rubric).  Once onboarding is complete this is set to 2."""

    completed: bool
    """True when the teacher has explicitly completed or dismissed the wizard."""

    trial_ends_at: datetime | None
    """ISO-8601 timestamp of when the teacher's trial period ends.
    ``None`` if the trial end date has not been set (e.g. email not yet
    verified)."""

    model_config = {"from_attributes": True}


class OnboardingCompleteResponse(BaseModel):
    """Response body for POST /api/v1/onboarding/complete."""

    message: str

    model_config = {"from_attributes": True}
