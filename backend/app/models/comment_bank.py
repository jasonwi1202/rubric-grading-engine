"""CommentBankEntry ORM model.

A reusable feedback comment snippet saved by a teacher for reuse during
grading.  Each entry is scoped to its owning teacher via ``teacher_id``.

The ``text`` field contains arbitrary teacher-entered content and may include
sensitive information, including student identifiers.  Do not log this field.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.models.base import Base


class CommentBankEntry(Base):
    """A saved feedback comment snippet owned by a teacher."""

    __tablename__ = "comment_bank_entries"

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
    text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
