"""Pydantic schemas for the rubric endpoints.

No student PII is collected, processed, or stored here.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field, model_validator


class RubricCriterionRequest(BaseModel):
    """A single criterion in a rubric creation or update request."""

    name: str = Field(min_length=1, max_length=255)
    description: str = ""
    weight: Decimal = Field(gt=Decimal("0"), le=Decimal("100"))
    min_score: int = Field(ge=1)
    max_score: int = Field(ge=1)
    anchor_descriptions: dict[str, str] | None = None

    @model_validator(mode="after")
    def max_score_gt_min_score(self) -> RubricCriterionRequest:
        if self.max_score <= self.min_score:
            raise ValueError("max_score must be greater than min_score")
        return self


class CreateRubricRequest(BaseModel):
    """Request body for POST /rubrics."""

    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    criteria: list[RubricCriterionRequest] = Field(min_length=1)


class PatchRubricRequest(BaseModel):
    """Request body for PATCH /rubrics/{rubricId}.

    Only fields that are explicitly included in the request body are updated.
    Use ``model_fields_set`` to determine which fields were provided.
    """

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    criteria: list[RubricCriterionRequest] | None = None


class RubricCriterionResponse(BaseModel):
    """A single criterion within a rubric response."""

    id: uuid.UUID
    name: str
    description: str
    weight: float
    min_score: int
    max_score: int
    display_order: int
    anchor_descriptions: dict[str, str] | None

    model_config = {"from_attributes": True}


class RubricResponse(BaseModel):
    """Full rubric response including all criteria."""

    id: uuid.UUID
    name: str
    description: str | None
    is_template: bool
    created_at: datetime
    updated_at: datetime
    criteria: list[RubricCriterionResponse]

    model_config = {"from_attributes": True}


class RubricListItemResponse(BaseModel):
    """Summary rubric item for GET /rubrics list response."""

    id: uuid.UUID
    name: str
    description: str | None
    is_template: bool
    created_at: datetime
    updated_at: datetime
    criterion_count: int

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Rubric template schemas
# ---------------------------------------------------------------------------


class SaveRubricAsTemplateRequest(BaseModel):
    """Request body for POST /rubric-templates.

    Saves a copy of an existing rubric as a personal template.
    """

    rubric_id: uuid.UUID
    name: str | None = Field(default=None, min_length=1, max_length=255)


class RubricTemplateListItemResponse(BaseModel):
    """Summary item returned by GET /rubric-templates."""

    id: uuid.UUID
    name: str
    description: str | None
    is_system: bool
    created_at: datetime
    updated_at: datetime
    criterion_count: int

    model_config = {"from_attributes": True}


class RubricTemplateResponse(BaseModel):
    """Full template response including criteria."""

    id: uuid.UUID
    name: str
    description: str | None
    is_system: bool
    created_at: datetime
    updated_at: datetime
    criteria: list[RubricCriterionResponse]

    model_config = {"from_attributes": True}
