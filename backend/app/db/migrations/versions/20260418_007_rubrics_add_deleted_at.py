"""rubrics: add deleted_at for soft delete

Revision ID: 007_rubrics_deleted_at
Revises: 006_core_schema
Create Date: 2026-04-18 00:00:00.000000

Adds a nullable TIMESTAMPTZ ``deleted_at`` column to ``rubrics`` to support
soft deletion.  All reads must filter ``deleted_at IS NULL``.  The DELETE
rubric endpoint sets this to the current timestamp instead of hard-deleting
the row, so that assignment rubric snapshots remain coherent.

Downgrade drops the column (safe — the column is nullable and the application
always re-adds it on the next upgrade).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "007_rubrics_deleted_at"
down_revision: str | None = "006_core_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "rubrics",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("rubrics", "deleted_at")
