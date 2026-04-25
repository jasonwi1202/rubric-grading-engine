"""grades: add server default 'grading-v1' to prompt_version column

Revision ID: 021_grades_prompt_version_default
Revises: 020_rls_tenant_isolation
Create Date: 2026-04-25 00:00:00.000000

The ``prompt_version`` column was added to ``grades`` in migration
006_core_schema as ``VARCHAR(100) NOT NULL`` without a server-side default.
This migration adds ``DEFAULT 'grading-v1'`` so that the column fully matches
the specification in ``docs/roadmap.md`` MX.5 and the ``grading-{version}``
format written by the grading service.

All existing rows already have an explicit value written by the grading
service, so no data back-fill is required.

Downgrade removes the server default.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "021_grades_prompt_version_default"
down_revision: str | None = "020_rls_tenant_isolation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Add server default matching the grading service's 'grading-{version}' format.
    op.alter_column(
        "grades",
        "prompt_version",
        existing_type=sa.String(100),
        server_default="grading-v1",
        existing_nullable=False,
    )


def downgrade() -> None:
    # Remove the server default, leaving the column NOT NULL with no default.
    op.alter_column(
        "grades",
        "prompt_version",
        existing_type=sa.String(100),
        server_default=None,
        existing_nullable=False,
    )
