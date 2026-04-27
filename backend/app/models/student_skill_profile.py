"""StudentSkillProfile ORM model.

A persistent, per-student aggregation of normalized skill scores across all
graded assignments.  Updated incrementally each time a grade is locked (via
the skill-profile Celery task introduced in M5-03).

Design decisions:
- ``teacher_id`` is stored directly on this table so that the RLS policy can
  use an efficient equality check (matching the pattern used by ``students``,
  ``classes``, etc.) rather than a multi-hop sub-query join.
- ``skill_scores`` is a JSONB column with the shape:
      {
        "<skill_name>": {
          "avg_score":    float,   # weighted average in [0, 1]
          "trend":        str,     # "improving" | "stable" | "declining"
          "data_points":  int,     # number of criterion scores contributing
          "last_updated": str      # ISO-8601 datetime string (UTC)
        },
        ...
      }
  Skill names are canonical dimension names (e.g. "thesis", "evidence",
  "organization") produced by the skill-normalization layer (M5-01).
- A unique constraint on ``(teacher_id, student_id)`` enforces one profile
  per student, matching the upsert path in the service layer.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.models.base import Base


class StudentSkillProfile(Base):
    """Aggregated skill profile for a student, updated after each grade lock."""

    __tablename__ = "student_skill_profiles"

    __table_args__ = (
        UniqueConstraint("teacher_id", "student_id", name="uq_skill_profile_teacher_student"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    teacher_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("students.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # JSONB shape: {skill_name: {avg_score, trend, data_points, last_updated}}
    skill_scores: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        server_default="'{}'::jsonb",
    )
    # Total number of graded assignments whose scores contributed to this profile.
    assignment_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    last_updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
