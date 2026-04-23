"""Pydantic schemas for the integrity report API endpoints.

No student PII is collected, processed, or stored here — only entity IDs
and integrity signal values.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

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

    model_config = {"from_attributes": True}


class IntegrityReportResponse(BaseModel):
    """Integrity report returned by GET /essays/{essayId}/integrity."""

    id: uuid.UUID
    essay_version_id: uuid.UUID
    provider: str
    # Probability [0.0, 1.0] that the text is AI-generated; None if not available.
    ai_likelihood: float | None
    # Overall similarity score [0.0, 1.0]; None if not available.
    similarity_score: float | None
    # Zero or more flagged passage excerpts. Never None — empty list when absent.
    flagged_passages: list[dict[str, Any]]
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

    def validate_teacher_action(self) -> None:
        """Raise ValueError if the status is not a valid teacher action."""
        allowed = {IntegrityReportStatus.reviewed_clear, IntegrityReportStatus.flagged}
        if self.status not in allowed:
            raise ValueError(
                f"Status must be one of: {', '.join(s.value for s in allowed)}."
            )


class IntegritySummaryResponse(BaseModel):
    """Aggregate integrity signal counts for an assignment (M4.6 class-level view)."""

    assignment_id: uuid.UUID
    flagged: int
    reviewed_clear: int
    pending: int
    total: int
