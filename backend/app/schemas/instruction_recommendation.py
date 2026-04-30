"""Pydantic schemas for instruction recommendation endpoints (M6-07).

No student PII is logged.  Student IDs appear in response bodies only,
never in log lines.

Endpoints:
  POST   /students/{studentId}/recommendations          — generate for student profile
  GET    /students/{studentId}/recommendations          — list persisted recs for student
  POST   /classes/{classId}/groups/{groupId}/recommendations — generate for skill-gap group
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from app.models.instruction_recommendation import InstructionRecommendation


class RecommendationStatus(StrEnum):
    """Teacher review lifecycle for a recommendation set."""

    pending_review = "pending_review"
    accepted = "accepted"
    dismissed = "dismissed"


class RecommendationItemResponse(BaseModel):
    """A single activity recommendation within a generated set.

    ``title`` is the activity objective.
    ``description`` + ``strategy_type`` + ``estimated_minutes`` describe the
    structure.
    ``skill_dimension`` identifies which skill gap the activity targets.
    """

    skill_dimension: str = Field(
        description="Canonical skill dimension targeted (e.g. 'thesis')."
    )
    title: str = Field(description="Short activity title — serves as the objective.")
    description: str = Field(
        description="Specific, actionable activity description — the structure."
    )
    estimated_minutes: int = Field(
        ge=1,
        description="Estimated activity duration in minutes.",
    )
    strategy_type: str = Field(
        description=(
            "Instructional strategy label, e.g. 'mini_lesson', 'guided_practice', "
            "'independent_practice', 'intervention'."
        )
    )


class InstructionRecommendationResponse(BaseModel):
    """Full instruction recommendation set as returned by the API.

    Matches the ``InstructionRecommendation`` ORM model.
    """

    id: uuid.UUID
    teacher_id: uuid.UUID
    student_id: uuid.UUID | None = Field(
        default=None,
        description="Populated for student-level recommendations.",
    )
    group_id: uuid.UUID | None = Field(
        default=None,
        description="Populated for group-level recommendations.",
    )
    worklist_item_id: uuid.UUID | None = Field(
        default=None,
        description="Set when generation was triggered from a worklist item.",
    )
    skill_key: str | None = Field(
        default=None,
        description=(
            "Target skill dimension key (e.g. 'evidence').  "
            "NULL when targeting all detected gaps."
        ),
    )
    grade_level: str = Field(
        description="Grade-level descriptor used in the LLM prompt (e.g. 'Grade 8')."
    )
    prompt_version: str = Field(
        description="Instruction prompt version used to generate this set."
    )
    recommendations: list[RecommendationItemResponse] = Field(
        description=(
            "List of recommended activities parsed from the LLM response.  "
            "May be empty if the model returned no items."
        )
    )
    evidence_summary: str = Field(
        description=(
            "Human-readable summary of the skill gaps that triggered generation."
        )
    )
    status: RecommendationStatus = Field(
        description="Teacher review lifecycle status."
    )
    created_at: datetime


class GenerateStudentRecommendationRequest(BaseModel):
    """Request body for POST /students/{studentId}/recommendations.

    Triggers LLM-based recommendation generation from the student's current
    skill profile.  The teacher supplies the grade level and desired activity
    duration; the system derives the skill gaps from the profile.
    """

    grade_level: str = Field(
        min_length=1,
        max_length=100,
        description="Grade-level descriptor for contextualising recommendations, e.g. 'Grade 8'.",
    )
    duration_minutes: int = Field(
        default=20,
        ge=5,
        le=120,
        description=(
            "Target activity duration in minutes.  "
            "Guides the LLM to produce activities of an appropriate length."
        ),
    )
    skill_key: str | None = Field(
        default=None,
        max_length=200,
        description=(
            "Optionally restrict generation to a single skill dimension "
            "(e.g. 'evidence').  When omitted, all detected gaps are considered."
        ),
    )
    worklist_item_id: uuid.UUID | None = Field(
        default=None,
        description=(
            "ID of the worklist item that triggered this generation.  "
            "When provided, the item is linked in the persisted recommendation."
        ),
    )


class GenerateGroupRecommendationRequest(BaseModel):
    """Request body for POST /classes/{classId}/groups/{groupId}/recommendations.

    Triggers LLM-based recommendation generation for a class skill-gap group.
    The group's shared skill gap is used as the generation context.
    """

    grade_level: str = Field(
        min_length=1,
        max_length=100,
        description="Grade-level descriptor for contextualising recommendations, e.g. 'Grade 8'.",
    )
    duration_minutes: int = Field(
        default=20,
        ge=5,
        le=120,
        description="Target activity duration in minutes.",
    )


def recommendation_response_from_orm(
    rec: InstructionRecommendation,
) -> InstructionRecommendationResponse:
    """Build an :class:`InstructionRecommendationResponse` from an ORM row.

    Shared by the students and classes routers to guarantee identical
    serialisation logic for both student-level and group-level recommendations.
    """
    items: list[Any] = rec.recommendations or []
    return InstructionRecommendationResponse(
        id=rec.id,
        teacher_id=rec.teacher_id,
        student_id=rec.student_id,
        group_id=rec.group_id,
        worklist_item_id=rec.worklist_item_id,
        skill_key=rec.skill_key,
        grade_level=rec.grade_level,
        prompt_version=rec.prompt_version,
        recommendations=[RecommendationItemResponse(**item) for item in items],
        evidence_summary=rec.evidence_summary,
        status=RecommendationStatus(rec.status),
        created_at=rec.created_at,
    )
