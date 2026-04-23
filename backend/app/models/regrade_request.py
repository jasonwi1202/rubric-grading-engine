"""RegradeRequest ORM model.

A RegradeRequest is a teacher-initiated request to reconsider an AI-generated
grade (or a specific criterion score within that grade).  The teacher supplies a
``dispute_text`` explaining why the result should be reconsidered, and the system
(or a privileged reviewer) records the outcome via ``status``, ``resolution_note``,
and ``resolved_at``.

``criterion_score_id`` is nullable — a request may target the grade as a whole
or a single criterion.  When present it references a ``CriterionScore`` row that
belongs to the same ``grade_id`` grade.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.grade import CriterionScore, Grade


class RegradeRequestStatus(enum.StrEnum):
    """Lifecycle status of a regrade request."""

    open = "open"
    approved = "approved"
    denied = "denied"


class RegradeRequest(Base):
    """A teacher's request to reconsider an AI grade or criterion score."""

    __tablename__ = "regrade_requests"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    grade_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "grades.id",
            ondelete="CASCADE",
            name="fk_regrade_requests_grades",
        ),
        nullable=False,
        index=True,
    )
    # Nullable — targets a specific criterion when set; targets the whole grade otherwise.
    criterion_score_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "criterion_scores.id",
            ondelete="SET NULL",
            name="fk_regrade_requests_criterion_scores",
        ),
        nullable=True,
        index=True,
    )
    teacher_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "users.id",
            ondelete="CASCADE",
            name="fk_regrade_requests_users",
        ),
        nullable=False,
        index=True,
    )
    dispute_text: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[RegradeRequestStatus] = mapped_column(
        Enum(RegradeRequestStatus, name="regraderequeststatus"),
        nullable=False,
        default=RegradeRequestStatus.open,
    )
    # Nullable — populated by the reviewer when the request is resolved.
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relationship to the grade this request targets.
    grade: Mapped[Grade] = relationship(
        "Grade",
        foreign_keys=[grade_id],
        lazy="raise",
    )
    # Relationship to the specific criterion score, if targeted.
    criterion_score: Mapped[CriterionScore | None] = relationship(
        "CriterionScore",
        foreign_keys=[criterion_score_id],
        lazy="raise",
    )
