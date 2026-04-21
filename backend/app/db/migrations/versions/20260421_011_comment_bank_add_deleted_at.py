"""comment_bank_entries: add deleted_at for soft delete

Revision ID: 011_comment_bank_deleted_at
Revises: 010_comment_bank
Create Date: 2026-04-21 00:00:00.000000

Adds a nullable TIMESTAMPTZ ``deleted_at`` column to ``comment_bank_entries``
to support soft deletion, matching the pattern established for ``rubrics`` in
migration 007.  All reads must filter ``deleted_at IS NULL``.  The DELETE
comment endpoint sets this to the current timestamp instead of hard-deleting
the row.

Downgrade drops the column (safe — the column is nullable).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "011_comment_bank_deleted_at"
down_revision: str | None = "010_comment_bank"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "comment_bank_entries",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("comment_bank_entries", "deleted_at")
