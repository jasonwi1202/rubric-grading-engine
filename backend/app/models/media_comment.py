"""MediaComment ORM model.

A MediaComment is a short audio recording attached to a Grade.  The media
file is stored in S3; only the metadata (S3 key, duration, MIME type) lives
here.

Security:
- ``s3_key`` follows the format ``media/{teacher_id}/{grade_id}/{uuid}.webm``
  so no student PII ever appears in the key.
- Access is always scoped to the owning teacher via ``teacher_id``.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.models.base import Base


class MediaComment(Base):
    """Audio recording attached to a Grade."""

    __tablename__ = "media_comments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    grade_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("grades.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Denormalised for tenant-scoped queries without extra joins.
    teacher_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # S3 object key: media/{teacher_id}/{grade_id}/{uuid}.webm
    s3_key: Mapped[str] = mapped_column(String(500), nullable=False)
    # Recording length in seconds (integer — MediaRecorder API duration).
    duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    # MIME type of the recorded blob, e.g. "audio/webm".
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    # True when the teacher has saved this comment to the media comment bank
    # so it can be reused across multiple essays.
    is_banked: Mapped[bool] = mapped_column(
        default=False,
        nullable=False,
        server_default="false",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
