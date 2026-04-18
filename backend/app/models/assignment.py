"""Assignment ORM model.

An assignment links a class to a rubric and collects student essay submissions.
The rubric is snapshotted at creation time into ``rubric_snapshot`` (JSONB) so
that later rubric edits do not retroactively affect grading.
"""

import enum
import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.models.base import Base


class AssignmentStatus(enum.StrEnum):
    """Lifecycle status of an assignment."""

    draft = "draft"
    open = "open"
    grading = "grading"
    review = "review"
    complete = "complete"
    returned = "returned"


class Assignment(Base):
    """An assignment within a class, linking a rubric snapshot to essays."""

    __tablename__ = "assignments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    class_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("classes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    rubric_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("rubrics.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    # Immutable snapshot of the rubric at assignment-creation time.
    # Grading always uses this snapshot, never the live rubric.
    rubric_snapshot: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[AssignmentStatus] = mapped_column(
        Enum(AssignmentStatus, name="assignmentstatus"),
        nullable=False,
        default=AssignmentStatus.draft,
    )
    resubmission_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    resubmission_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
