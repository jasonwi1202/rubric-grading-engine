"""Essay and EssayVersion ORM models.

An Essay represents a student's submission slot for an assignment — one essay
per student per assignment.  Actual content lives in EssayVersion records,
which track the original submission and any resubmissions.
"""

import enum
import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
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
    # Nullable — populated by the compute_essay_embedding Celery task after
    # text extraction.  Stores a 1 536-dimension OpenAI embedding vector used
    # for internal cosine-similarity plagiarism detection.
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1536), nullable=True)
    # Nullable — present only for essays composed in the browser writing
    # interface (M5-09).  Stores an ordered list of snapshot dicts:
    # [{"seq": int, "ts": str, "word_count": int, "html_content": str}, ...]
    # NULL for file-upload essays (no writing-process data captured).
    writing_snapshots: Mapped[list[Any] | None] = mapped_column(JSONB, nullable=True, default=None)
    # Nullable — populated lazily by GET /essays/{id}/process-signals (M5-10).
    # Stores the derived composition timeline signals as a single JSONB object
    # so subsequent requests can return the cached result without re-computing.
    # NULL until first requested; re-computed if writing_snapshots is updated.
    process_signals: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True, default=None
    )
