"""IntegrityReport ORM model.

An IntegrityReport records the result of an AI-integrity or plagiarism check
run against a specific essay version.  Each report is scoped to a teacher via
``teacher_id`` and references the essay version that was checked via
``essay_version_id``.

``flagged_passages`` stores zero or more passage excerpts that triggered the
integrity check, as a JSONB array.  It is nullable for reports where the
provider did not return passage-level detail.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, Float, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.essay import EssayVersion


class IntegrityReportStatus(enum.StrEnum):
    """Review status of an integrity report."""

    pending = "pending"
    reviewed_clear = "reviewed_clear"
    flagged = "flagged"


class IntegrityReport(Base):
    """AI-integrity or plagiarism check result for a specific essay version."""

    __tablename__ = "integrity_reports"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    essay_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "essay_versions.id",
            ondelete="CASCADE",
            name="fk_integrity_reports_essay_versions",
        ),
        nullable=False,
        index=True,
    )
    teacher_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "users.id",
            ondelete="CASCADE",
            name="fk_integrity_reports_users",
        ),
        nullable=False,
        index=True,
    )
    # Name of the integrity-check provider, e.g. "gptzero", "originality_ai".
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    # Probability [0.0, 1.0] that the text is AI-generated, as returned by the provider.
    ai_likelihood: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Similarity score [0.0, 1.0] vs. known sources, as returned by the provider.
    similarity_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Zero or more passage excerpts that triggered the check; provider-specific structure.
    flagged_passages: Mapped[list[dict[str, object]] | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[IntegrityReportStatus] = mapped_column(
        Enum(IntegrityReportStatus, name="integritystatus"),
        nullable=False,
        default=IntegrityReportStatus.pending,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationship to the essay version this report was generated for.
    essay_version: Mapped[EssayVersion] = relationship(
        "EssayVersion",
        foreign_keys=[essay_version_id],
        lazy="raise",
    )
