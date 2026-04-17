"""create dpa_requests table

Revision ID: 002_dpa_requests
Revises: 001_contact_inquiries
Create Date: 2026-04-17 00:01:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "002_dpa_requests"
down_revision: str | None = "001_contact_inquiries"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "dpa_requests",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("school_name", sa.String(300), nullable=False),
        sa.Column("district", sa.String(300), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("submitter_ip", sa.String(45), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_dpa_requests_created_at",
        "dpa_requests",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_dpa_requests_created_at", table_name="dpa_requests")
    op.drop_table("dpa_requests")
