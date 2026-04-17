"""add onboarding_complete and trial_ends_at to users

Revision ID: 005_users_onboarding
Revises: 004_audit_logs
Create Date: 2026-04-17 00:05:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "005_users_onboarding"
down_revision: str | None = "004_audit_logs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "onboarding_complete",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "users",
        sa.Column("trial_ends_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "trial_ends_at")
    op.drop_column("users", "onboarding_complete")
