"""integrity_report: add reviewed_at column

Revision ID: 016_integrity_report_reviewed_at
Revises: 015_integrity_report_unique_version_provider
Create Date: 2026-04-23 03:00:00.000000

Adds the nullable ``reviewed_at`` timestamp column to ``integrity_reports``
so that the M4.6 status-update endpoint can record when a teacher reviewed
the report.

Zero-downtime: adding a nullable column with no default does not require
a table rewrite or an exclusive lock on any supported PostgreSQL version.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "016_integrity_report_reviewed_at"
down_revision: str | None = "015_ir_unique_version_provider"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "integrity_reports",
        sa.Column(
            "reviewed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("integrity_reports", "reviewed_at")
