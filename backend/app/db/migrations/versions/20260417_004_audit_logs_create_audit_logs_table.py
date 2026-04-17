"""create audit_logs table

Revision ID: 004_audit_logs
Revises: 003_users
Create Date: 2026-04-17 00:03:00.000000

This migration creates indexes CONCURRENTLY and must run outside a transaction.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "004_audit_logs"
down_revision: str | None = "003_users"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "audit_logs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("teacher_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("entity_type", sa.String(50), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("before_value", postgresql.JSONB(), nullable=True),
        sa.Column("after_value", postgresql.JSONB(), nullable=True),
        sa.Column("ip_address", postgresql.INET(), nullable=True),
        sa.Column("metadata", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    # Composite indexes for the query patterns documented in data-model.md.
    op.create_index(
        "ix_audit_logs_entity_type_entity_id",
        "audit_logs",
        ["entity_type", "entity_id"],
    )
    op.create_index(
        "ix_audit_logs_teacher_id_created_at",
        "audit_logs",
        ["teacher_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_audit_logs_action_created_at",
        "audit_logs",
        ["action", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_audit_logs_action_created_at", table_name="audit_logs")
    op.drop_index("ix_audit_logs_teacher_id_created_at", table_name="audit_logs")
    op.drop_index("ix_audit_logs_entity_type_entity_id", table_name="audit_logs")
    op.drop_table("audit_logs")
