"""Rubric and RubricCriterion ORM models.

A Rubric is a reusable grading template owned by a teacher.
RubricCriteria define the individual scored dimensions within a rubric.

When an Assignment is created, the rubric is snapshotted into
``assignment.rubric_snapshot`` (JSONB) so that later rubric edits do not
affect grades already in progress.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.models.base import Base


class Rubric(Base):
    """A reusable grading rubric owned by a teacher."""

    __tablename__ = "rubrics"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    teacher_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_template: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    # Soft-delete timestamp.  NULL means the rubric is active.
    # Set to the deletion timestamp when the teacher deletes the rubric.
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class RubricCriterion(Base):
    """A single scored criterion within a rubric."""

    __tablename__ = "rubric_criteria"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    rubric_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("rubrics.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    # Percentage weight; all criteria within a rubric must sum to 100.
    weight: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    min_score: Mapped[int] = mapped_column(Integer, nullable=False)
    max_score: Mapped[int] = mapped_column(Integer, nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False)
    # Nullable — score-level exemplars, e.g. {"1": "...", "5": "..."}.
    # JSON object keys are always strings; values are the description text.
    anchor_descriptions: Mapped[dict[str, str] | None] = mapped_column(JSONB, nullable=True)
