"""Pydantic schemas for the account endpoints.

No student PII is collected, processed, or stored here.
"""

from datetime import datetime

from pydantic import BaseModel


class TrialStatusResponse(BaseModel):
    """Response body for GET /api/v1/account/trial."""

    trial_ends_at: datetime | None
    """ISO-8601 timestamp of when the teacher's trial period ends.
    ``None`` if the trial end date has not been set (e.g. email not yet
    verified)."""

    is_active: bool
    """True when the trial is currently active (``trial_ends_at`` is in the
    future or not set)."""

    days_remaining: int | None
    """Number of full calendar days remaining in the trial.  ``None`` if
    ``trial_ends_at`` is not set.  Zero or negative means the trial has
    expired."""

    model_config = {"from_attributes": True}
