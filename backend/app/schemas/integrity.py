"""Pydantic schemas for the integrity report API endpoints.

Responses may include flagged passage excerpts from student essays.  Because
excerpt text can contain student PII, any such response data must be handled
as FERPA-protected student data.  Student PII must not be logged from these
schemas; use entity IDs and integrity signal values in logs instead.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.models.integrity_report import IntegrityReportStatus


class FlaggedPassage(BaseModel):
    """One flagged passage excerpt from an integrity check."""

    text: str
    ai_probability: float | None = None
    # start_char/end_char are optional — not all providers return offsets.
    start_char: int | None = None
    end_char: int | None = None
    signal_type: str | None = None
    source: str | None = None

    model_config = {"from_attributes": True, "extra": "ignore"}


class IntegrityReportResponse(BaseModel):
    """Integrity report returned by GET /essays/{essayId}/integrity."""

    id: uuid.UUID
    essay_id: uuid.UUID
    essay_version_id: uuid.UUID
    provider: str
    # Probability [0.0, 1.0] that the text is AI-generated; None if not available.
    ai_likelihood: float | None
    # Overall similarity score [0.0, 1.0]; None if not available.
    similarity_score: float | None
    # Zero or more flagged passage excerpts. Never None — empty list when absent.
    flagged_passages: list[FlaggedPassage]
    status: IntegrityReportStatus
    reviewed_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PatchIntegrityStatusRequest(BaseModel):
    """Request body for PATCH /integrity-reports/{id}/status.

    Only the two teacher-action statuses are accepted:
    - ``reviewed_clear``: teacher has reviewed and found no concern.
    - ``flagged``:        teacher confirms the integrity concern.
    """

    status: IntegrityReportStatus = Field(
        ...,
        description="Must be 'reviewed_clear' or 'flagged'.",
    )

    @field_validator("status")
    @classmethod
    def validate_teacher_action(cls, v: IntegrityReportStatus) -> IntegrityReportStatus:
        """Raise ValueError if the status is not a valid teacher action."""
        allowed = {IntegrityReportStatus.reviewed_clear, IntegrityReportStatus.flagged}
        if v not in allowed:
            raise ValueError(f"Status must be one of: {', '.join(s.value for s in allowed)}.")
        return v


class IntegritySummaryResponse(BaseModel):
    """Aggregate integrity signal counts for an assignment (M4.6 class-level view)."""

    assignment_id: uuid.UUID
    flagged: int
    reviewed_clear: int
    pending: int
    total: int
