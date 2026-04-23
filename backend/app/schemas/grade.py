"""Pydantic schemas for the grade read and edit endpoints.

No student PII is collected, processed, or stored here.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field, model_validator

from app.models.grade import ConfidenceLevel, StrictnessLevel


class CriterionScoreResponse(BaseModel):
    """Per-criterion score within a grade response."""

    id: uuid.UUID
    rubric_criterion_id: uuid.UUID
    ai_score: int
    teacher_score: int | None
    final_score: int
    ai_justification: str
    ai_feedback: str | None
    teacher_feedback: str | None
    confidence: ConfidenceLevel
    created_at: datetime

    model_config = {"from_attributes": True}


class GradeResponse(BaseModel):
    """Full grade response returned by GET /essays/{essayId}/grade."""

    id: uuid.UUID
    essay_version_id: uuid.UUID
    total_score: Decimal
    max_possible_score: Decimal
    summary_feedback: str
    summary_feedback_edited: str | None
    strictness: StrictnessLevel
    ai_model: str
    prompt_version: str
    is_locked: bool
    locked_at: datetime | None
    # Derived from criterion confidence levels. Nullable for pre-M4.1 grades.
    overall_confidence: ConfidenceLevel | None
    created_at: datetime
    criterion_scores: list[CriterionScoreResponse]

    model_config = {"from_attributes": True}


class PatchFeedbackRequest(BaseModel):
    """Request body for PATCH /grades/{gradeId}/feedback."""

    summary_feedback: str = Field(min_length=1, max_length=10000)


class PatchCriterionRequest(BaseModel):
    """Request body for PATCH /grades/{gradeId}/criteria/{criterionId}.

    At least one of ``teacher_score`` or ``teacher_feedback`` must be provided.
    Both fields are optional to allow score-only or feedback-only updates.
    """

    teacher_score: int | None = None
    teacher_feedback: str | None = Field(default=None, max_length=5000)

    @model_validator(mode="after")
    def at_least_one_field_required(self) -> PatchCriterionRequest:
        if self.teacher_score is None and self.teacher_feedback is None:
            raise ValueError("At least one of teacher_score or teacher_feedback must be provided.")
        return self


class AuditLogEntryResponse(BaseModel):
    """A single audit log entry for a grade's change history.

    ``before_value`` and ``after_value`` contain the raw JSONB payloads stored
    in ``audit_logs`` and may include free-form text (e.g. feedback strings)
    that should be treated as sensitive.  Application log statements for this
    read path use only entity IDs.
    """

    id: uuid.UUID
    # Nullable — system-generated events (e.g., score_clamped) may have no
    # acting teacher.
    teacher_id: uuid.UUID | None
    entity_type: str
    # This endpoint only returns audit entries scoped to a specific grade or
    # criterion_score record, so entity_id is always present in the response.
    entity_id: uuid.UUID
    action: str
    before_value: dict[str, Any] | None
    after_value: dict[str, Any] | None
    created_at: datetime

    model_config = {"from_attributes": True}
