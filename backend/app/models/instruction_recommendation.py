"""InstructionRecommendation ORM model.

Stores AI-generated instruction recommendations produced from student skill
profiles or class skill-gap groups.  One row per generation request.

Design decisions:
- ``teacher_id`` is stored directly on this table so the RLS policy can use an
  efficient equality check (matching the pattern used by all other
  tenant-scoped tables).
- Either ``student_id`` or ``group_id`` (but not both) identifies the
  generation context.  Both are nullable so the CHECK constraint documents
  this intent at the application layer.
- ``worklist_item_id`` is nullable — generation can be triggered from a
  worklist item *or* directly from the student/group profile.
- ``recommendations`` is a JSONB array of serialised
  :class:`~app.llm.parsers.ParsedRecommendation` objects, validated by the
  parser before being written.
- ``evidence_summary`` is a short human-readable description of which skill
  gaps triggered the recommendation, built from the skill profile at
  generation time.
- ``status`` tracks the teacher's review lifecycle:
  'pending_review' → 'accepted' | 'dismissed'.
- ``prompt_version`` records which instruction prompt module was used so that
  recommendations generated with an older prompt can be identified.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.models.base import Base


class InstructionRecommendation(Base):
    """One AI-generated instruction recommendation set for a student or group."""

    __tablename__ = "instruction_recommendations"
    __table_args__ = (
        CheckConstraint(
            "(student_id IS NOT NULL AND group_id IS NULL)"
            " OR (student_id IS NULL AND group_id IS NOT NULL)",
            name="ck_instruction_recommendations_context_exclusive",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    teacher_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE", name="fk_instruction_recommendations_users"),
        nullable=False,
        index=True,
    )
    # Exactly one of student_id / group_id is populated per row.
    student_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "students.id",
            ondelete="CASCADE",
            name="fk_instruction_recommendations_students",
        ),
        nullable=True,
        index=True,
    )
    group_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "student_groups.id",
            ondelete="CASCADE",
            name="fk_instruction_recommendations_student_groups",
        ),
        nullable=True,
        index=True,
    )
    # Optional — set when generation was triggered from a worklist item.
    worklist_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "teacher_worklist_items.id",
            ondelete="SET NULL",
            name="fk_instruction_recommendations_worklist_items",
        ),
        nullable=True,
    )
    # Canonical skill dimension key (e.g. 'evidence').  NULL if the
    # recommendation targets all detected gaps rather than a single skill.
    skill_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # Grade-level descriptor used in the prompt (e.g. 'Grade 8').
    grade_level: Mapped[str] = mapped_column(String(100), nullable=False)
    # Prompt version used (e.g. 'instruction-v1').
    prompt_version: Mapped[str] = mapped_column(String(50), nullable=False)
    # Validated JSONB array of recommendation objects.
    # Shape: [{"skill_dimension": str, "title": str, "description": str,
    #           "estimated_minutes": int, "strategy_type": str}, ...]
    recommendations: Mapped[list[Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default="'[]'::jsonb",
    )
    # Human-readable summary of the skill gaps that triggered this generation.
    evidence_summary: Mapped[str] = mapped_column(Text, nullable=False)
    # Teacher review lifecycle: 'pending_review' | 'accepted' | 'dismissed'
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default="'pending_review'",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
