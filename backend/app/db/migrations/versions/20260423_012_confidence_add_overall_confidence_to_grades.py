"""confidence: add overall_confidence to grades

Revision ID: 012_confidence_scoring
Revises: 011_comment_bank_deleted_at
Create Date: 2026-04-23 00:00:00.000000

Adds the overall_confidence column introduced by M4.1:

  - Adds ``overall_confidence`` column to ``grades`` (VARCHAR(10), nullable).
    Nullable so that existing grade rows written before M4.1 are valid without
    a back-fill pass.  New rows written by the grading service always have a
    value derived from the constituent criterion confidence levels.

The ``confidence`` column on ``criterion_scores`` was added in migration
006_core_schema and requires no change here.

Downgrade removes the column.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "012_confidence_scoring"
down_revision: str | None = "011_comment_bank_deleted_at"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Add overall_confidence to grades (nullable — existing rows pre-date M4.1).
    op.add_column(
        "grades",
        sa.Column("overall_confidence", sa.String(10), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("grades", "overall_confidence")
