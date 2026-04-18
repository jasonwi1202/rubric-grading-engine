"""ClassEnrollment ORM model.

Join table linking students to classes.  Tracks enrollment history; a student
can be soft-removed via ``removed_at`` without losing data.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.models.base import Base


class ClassEnrollment(Base):
    """Links a student to a class; supports soft-removal via removed_at."""

    __tablename__ = "class_enrollments"

    # The active-enrollment uniqueness constraint (class_id, student_id WHERE
    # removed_at IS NULL) is enforced by a partial unique index created in the
    # migration.  A full ORM UniqueConstraint cannot express the WHERE clause,
    # so it is intentionally omitted here.

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
