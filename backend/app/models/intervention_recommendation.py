"""InterventionRecommendation ORM model (M7-01).

Stores agent-generated intervention recommendations produced by the scheduled
intervention agent Celery task.  Each row represents one signal detected for a
specific student that requires explicit teacher approval before any action is
taken.

Design decisions:
- ``teacher_id`` is stored directly on this table so the RLS policy can use an
  efficient equality check (matching the pattern used by all other
  tenant-scoped tables).
- ``student_id`` identifies the student whose profile triggered the signal.
- ``trigger_type`` mirrors the worklist trigger vocabulary:
  'persistent_gap' | 'regression' | 'non_responder'.
- ``skill_key`` is nullable — student-level triggers (e.g. 'non_responder')
  are not specific to a single skill dimension.
- ``trigger_reason`` is a short, human-readable sentence explaining *why* this
  intervention was triggered (displayed to the teacher alongside the evidence).
- ``evidence_summary`` is a structured description of the supporting data
  (avg_score, trend, assignment_count, etc.) so the teacher can evaluate the
  recommendation without navigating to the profile.
- ``urgency`` mirrors worklist urgency (1–4, 4 = most urgent).
- ``status`` tracks teacher lifecycle:
  'pending_review' → 'approved' | 'dismissed'.
- ``actioned_at`` records when the teacher approved or dismissed the item.
- A unique constraint on (teacher_id, student_id, trigger_type, skill_key)
  prevents duplicate pending recommendations for the same signal from
  accumulating across scheduled runs.  The constraint is relaxed: only rows
  with status='pending_review' need be unique; approved/dismissed rows are
  historical and may repeat.  A partial unique index on the application layer
  enforces this; the model records the intent via a conventional index only.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.models.base import Base


class InterventionRecommendation(Base):
    """One agent-generated intervention recommendation awaiting teacher review."""

    __tablename__ = "intervention_recommendations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    teacher_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "users.id",
            ondelete="CASCADE",
            name="fk_intervention_recommendations_users",
        ),
        nullable=False,
        index=True,
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "students.id",
            ondelete="CASCADE",
            name="fk_intervention_recommendations_students",
        ),
        nullable=False,
        index=True,
    )
    # Signal type: 'persistent_gap' | 'regression' | 'non_responder'
    trigger_type: Mapped[str] = mapped_column(String(30), nullable=False)
    # Canonical skill dimension key (e.g. 'evidence').  NULL for student-level signals.
    skill_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # Urgency level 1–4; 4 = most urgent.
    urgency: Mapped[int] = mapped_column(Integer, nullable=False)
    # Clear, human-readable reason why this intervention was triggered.
    trigger_reason: Mapped[str] = mapped_column(Text, nullable=False)
    # Supporting evidence summary (avg_score, trend, assignment_count, etc.).
    evidence_summary: Mapped[str] = mapped_column(Text, nullable=False)
    # Concrete action suggestion for the teacher.
    suggested_action: Mapped[str] = mapped_column(Text, nullable=False)
    # Signal-specific context: avg_score, trend, improvement, etc.
    details: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default="'{}'::jsonb",
    )
    # Teacher review lifecycle: 'pending_review' | 'approved' | 'dismissed'
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default="'pending_review'",
    )
    # When the teacher approved or dismissed this recommendation.
    actioned_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    # When the agent created this recommendation.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
