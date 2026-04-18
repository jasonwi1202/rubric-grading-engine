"""ClassEnrollment ORM model.

Join table linking students to classes.  Tracks enrollment history; a student
can be soft-removed via ``removed_at`` without losing data.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.models.base import Base


class ClassEnrollment(Base):
    """Links a student to a class; supports soft-removal via removed_at."""

    __tablename__ = "class_enrollments"

    __table_args__ = (
        # Partial unique constraint: a student can only be actively enrolled
        # in a class once (removed_at IS NULL).  Postgres enforces this as a
        # partial index.  See data-model.md for details.
        UniqueConstraint("class_id", "student_id", name="uq_class_enrollments_active"),
    )

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
    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("students.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    enrolled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    # Soft removal — set to the timestamp of removal; NULL means currently enrolled.
    removed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
