"""create comment_bank_entries table

Revision ID: 010_comment_bank
Revises: 009_feedback_tone
Create Date: 2026-04-21 00:00:00.000000

Creates the ``comment_bank_entries`` table introduced by M3.19.

Each row represents a reusable feedback snippet saved by a teacher.
The table is scoped to a teacher via ``teacher_id`` and is indexed on that
column for fast per-teacher list queries.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "010_comment_bank"
down_revision: str | None = "009_feedback_tone"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "comment_bank_entries",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "teacher_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", name="fk_comment_bank_entries_users", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_comment_bank_entries_teacher_id",
        "comment_bank_entries",
        ["teacher_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_comment_bank_entries_teacher_id", table_name="comment_bank_entries")
    op.drop_table("comment_bank_entries")
