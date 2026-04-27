"""Pydantic schemas for the student and enrollment endpoints.

No essay content or grade values appear here — those live on separate schemas.
Student PII (name) is present in responses; it is never logged.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field, model_validator


class StudentResponse(BaseModel):
    """Full student response — used in all student-related endpoints."""

    id: uuid.UUID
    teacher_id: uuid.UUID
    full_name: str
    external_id: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class SkillDimensionResponse(BaseModel):
    """Per-skill-dimension metadata within a student skill profile."""

    avg_score: float
    trend: str  # "improving" | "stable" | "declining"
    data_points: int
    last_updated: str  # ISO-8601 UTC datetime string


class SkillProfileResponse(BaseModel):
    """Aggregated skill profile embedded in the student detail response."""

    skill_scores: dict[str, SkillDimensionResponse]
    assignment_count: int
    last_updated_at: datetime

    model_config = {"from_attributes": True}


class StudentWithProfileResponse(BaseModel):
    """Student detail with an optional embedded skill profile.

    ``skill_profile`` is ``null`` when the student has no locked grades yet.
    """

    id: uuid.UUID
    teacher_id: uuid.UUID
    full_name: str
    external_id: str | None
    created_at: datetime
    skill_profile: SkillProfileResponse | None


class AssignmentHistoryItemResponse(BaseModel):
    """A single graded assignment in a student's chronological history."""

    assignment_id: uuid.UUID
    assignment_title: str
    class_id: uuid.UUID
    grade_id: uuid.UUID
    essay_id: uuid.UUID
    total_score: Decimal
    max_possible_score: Decimal
    locked_at: datetime


class EnrolledStudentResponse(BaseModel):
    """Response item returned from GET/POST /classes/{classId}/students.

    Combines the persistent student record with the enrollment metadata.
    """

    enrollment_id: uuid.UUID
    enrolled_at: datetime
    student: StudentResponse

    model_config = {"from_attributes": True}


class EnrollStudentRequest(BaseModel):
    """Request body for POST /classes/{classId}/students.

    Exactly one of ``student_id`` or ``full_name`` must be supplied:
    - Provide ``student_id`` to enroll an existing student owned by this teacher.
    - Provide ``full_name`` (and optionally ``external_id``) to create a new
      student record and immediately enroll them.
    """

    student_id: uuid.UUID | None = Field(
        default=None,
        description="ID of an existing student to enroll.  Mutually exclusive with full_name.",
    )
    full_name: str | None = Field(
        default=None,
        min_length=1,
        max_length=255,
        description="Name for a new student.  Mutually exclusive with student_id.",
    )
    external_id: str | None = Field(
        default=None,
        max_length=255,
        description="Optional LMS student ID.  Ignored when student_id is provided.",
    )

    @model_validator(mode="after")
    def _exactly_one_identifier(self) -> EnrollStudentRequest:
        if self.student_id is None and self.full_name is None:
            raise ValueError("Either 'student_id' or 'full_name' must be provided.")
        if self.student_id is not None and self.full_name is not None:
            raise ValueError("Provide 'student_id' or 'full_name', not both.")
        return self


class PatchStudentRequest(BaseModel):
    """Request body for PATCH /students/{studentId}.

    Only fields explicitly included in the request body are updated.
    Use ``model_fields_set`` to determine which fields were provided.
    """

    full_name: str | None = Field(default=None, min_length=1, max_length=255)
    external_id: str | None = Field(default=None, max_length=255)
