"""media_comment: add is_banked column to media_comments

Revision ID: 019_media_comment_is_banked
Revises: 018_media_comment
Create Date: 2026-04-24 00:00:00.000000

Adds ``is_banked`` boolean column to ``media_comments`` so teachers can save
a recorded comment to their reusable media comment bank (M4.12).

Zero-downtime notes:
- New column added with a NOT NULL + DEFAULT so existing rows get ``false``
  immediately without a table rewrite on PostgreSQL 11+.
- The column default avoids the need for a concurrent data migration.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "019_media_comment_is_banked"
down_revision: str | None = "018_media_comment"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "media_comments",
        sa.Column(
            "is_banked",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("media_comments", "is_banked")
