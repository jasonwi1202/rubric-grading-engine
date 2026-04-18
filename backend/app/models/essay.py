"""Essay and EssayVersion ORM models.

An Essay represents a student's submission slot for an assignment — one essay
per student per assignment.  Actual content lives in EssayVersion records,
which track the original submission and any resubmissions.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.models.base import Base


class EssayStatus(enum.StrEnum):
    """Lifecycle status of an essay submission."""

    unassigned = "unassigned"
    queued = "queued"
    grading = "grading"
    graded = "graded"
    reviewed = "reviewed"
    locked = "locked"
    returned = "returned"


class Essay(Base):
    """A student's submission slot for an assignment."""

    __tablename__ = "essays"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    assignment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("assignments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Nullable until the file is assigned to a student.
    student_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("students.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    status: Mapped[EssayStatus] = mapped_column(
        Enum(EssayStatus, name="essaystatus"),
        nullable=False,
        default=EssayStatus.unassigned,
    )
    submitted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class EssayVersion(Base):
    """A specific version of an essay — original or resubmission."""

    __tablename__ = "essay_versions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    essay_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("essays.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # 1 = original submission; 2+ = resubmissions.
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # Nullable — S3 key for the original uploaded file; may be absent for
    # paste/typed submissions.
    file_storage_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    word_count: Mapped[int] = mapped_column(Integer, nullable=False)
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
