"""audit_logs: validate fk_audit_logs_users constraint

Revision ID: 032_validate_audit_logs_users_fk
Revises: 031_revision_comparisons
Create Date: 2026-05-01 09:00:00.000000

Validates the previously-added NOT VALID foreign key on
``audit_logs.teacher_id -> users.id`` so existing rows are now covered by the
constraint as well.

The original FK was added as NOT VALID in migration 006 to avoid a long lock
while historical rows were being backfilled/verified.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "032_validate_audit_logs_users_fk"
down_revision: str | None = "031_revision_comparisons"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(sa.text("ALTER TABLE audit_logs VALIDATE CONSTRAINT fk_audit_logs_users"))


def downgrade() -> None:
    # PostgreSQL does not support toggling an existing FK back to NOT VALID.
    # Recreate the same constraint as NOT VALID to restore the pre-upgrade state.
    op.execute(sa.text("ALTER TABLE audit_logs DROP CONSTRAINT IF EXISTS fk_audit_logs_users"))
    op.execute(
        sa.text(
            """
            ALTER TABLE audit_logs
            ADD CONSTRAINT fk_audit_logs_users
            FOREIGN KEY (teacher_id)
            REFERENCES users (id)
            ON DELETE RESTRICT
            NOT VALID
            """
        )
    )
