"""RevisionComparison ORM model.

Stores the per-criterion score deltas, low-effort flag, and feedback-addressed
analysis produced after grading a resubmitted essay version (M6-11).

One RevisionComparison row is created for each resubmission grading event.
It links the base (previous) and revised (new) EssayVersion / Grade pairs and
captures the full comparison in JSONB columns so the frontend can render delta
indicators without additional joins.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Numeric
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.models.base import Base


class RevisionComparison(Base):
    """Comparison record produced after grading a resubmitted essay version.

    Columns:
        id: Primary key.
        essay_id: FK → essays.id.  Scopes the comparison to the parent essay.
        base_version_id: The EssayVersion that was the prior submission.
        revised_version_id: The EssayVersion that was just graded.
        base_grade_id: Grade record for the base version.
        revised_grade_id: Grade record for the revised version.
        total_score_delta: ``revised.total_score − base.total_score``.
        criterion_deltas: JSON array of per-criterion delta objects:
            ``[{criterion_id, base_score, revised_score, delta}, ...]``.
        is_low_effort: ``True`` when heuristics indicate a surface-level
            revision with no substantive change.
        low_effort_reasons: JSON array of human-readable reason strings
            explaining why the revision was flagged as low-effort.
        feedback_addressed: JSON array produced by the LLM analysis, or
            ``None`` when the LLM step was skipped or failed:
            ``[{criterion_id, feedback_given, addressed, detail}, ...]``.
        created_at: Row creation timestamp.
    """

    __tablename__ = "revision_comparisons"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    essay_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("essays.id", ondelete="CASCADE", name="fk_revision_comparisons_essays"),
        nullable=False,
        index=True,
    )
    base_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "essay_versions.id",
            ondelete="CASCADE",
            name="fk_revision_comparisons_essay_versions_base",
        ),
        nullable=False,
    )
    revised_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "essay_versions.id",
            ondelete="CASCADE",
            name="fk_revision_comparisons_essay_versions_revised",
        ),
        nullable=False,
        index=True,
    )
    base_grade_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("grades.id", ondelete="CASCADE", name="fk_revision_comparisons_grades_base"),
        nullable=False,
    )
    revised_grade_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("grades.id", ondelete="CASCADE", name="fk_revision_comparisons_grades_revised"),
        nullable=False,
    )
    # revised.total_score − base.total_score (may be negative for regressions)
    total_score_delta: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    # [{criterion_id, base_score, revised_score, delta}, ...]
    criterion_deltas: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)
    # True when heuristics indicate a surface-level (low-effort) revision.
    is_low_effort: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Human-readable reasons for the low-effort flag.  Empty list when not flagged.
    low_effort_reasons: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    # LLM-produced per-criterion feedback-addressed analysis.
    # NULL when LLM step was skipped or failed.
    # [{criterion_id, feedback_given, addressed: bool, detail: str}, ...]
    feedback_addressed: Mapped[list[Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
