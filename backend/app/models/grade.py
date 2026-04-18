"""Grade and CriterionScore ORM models.

A Grade is the grading result for a specific EssayVersion.  CriterionScore
records hold the per-criterion AI score and any teacher override.

``final_score`` on CriterionScore is always ``teacher_score ?? ai_score``
(COALESCE).  Application code must keep it in sync whenever ai_score or
teacher_score is written.
"""

import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.models.base import Base


class StrictnessLevel(enum.StrEnum):
    """Grading strictness setting applied at grade-generation time."""

    lenient = "lenient"
    balanced = "balanced"
    strict = "strict"


class ConfidenceLevel(enum.StrEnum):
    """LLM confidence in a criterion score."""

    high = "high"
    medium = "medium"
    low = "low"


class Grade(Base):
    """The grading result for a specific essay version."""

    __tablename__ = "grades"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    essay_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("essay_versions.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    total_score: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    max_possible_score: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    summary_feedback: Mapped[str] = mapped_column(Text, nullable=False)
    # Nullable — set only if the teacher edits the AI-generated summary.
    summary_feedback_edited: Mapped[str | None] = mapped_column(Text, nullable=True)
    strictness: Mapped[StrictnessLevel] = mapped_column(
        Enum(StrictnessLevel, name="strictnesslevel"),
        nullable=False,
    )
    # Model identifier, e.g. "gpt-4o-2024-08-06".
    ai_model: Mapped[str] = mapped_column(String(100), nullable=False)
    # Prompt version string that produced this grade, e.g. "grading-v1".
    prompt_version: Mapped[str] = mapped_column(String(100), nullable=False)
    is_locked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class CriterionScore(Base):
    """Per-criterion score within a grade.

    ``final_score`` is always COALESCE(teacher_score, ai_score).  Application
    code must update it whenever either source score changes.
    """

    __tablename__ = "criterion_scores"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    grade_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("grades.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    rubric_criterion_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("rubric_criteria.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    ai_score: Mapped[int] = mapped_column(Integer, nullable=False)
    # Nullable — set only if the teacher overrides the AI score.
    teacher_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # COALESCE(teacher_score, ai_score) — always kept in sync by the application.
    final_score: Mapped[int] = mapped_column(Integer, nullable=False)
    ai_justification: Mapped[str] = mapped_column(Text, nullable=False)
    # Nullable — teacher-written criterion-level feedback.
    teacher_feedback: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[ConfidenceLevel] = mapped_column(
        Enum(ConfidenceLevel, name="confidencelevel"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
