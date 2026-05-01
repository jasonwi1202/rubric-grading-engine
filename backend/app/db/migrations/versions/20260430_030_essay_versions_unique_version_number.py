"""essay_versions: add unique constraint on (essay_id, version_number)

Revision ID: 030_ev_unique_version_number
Revises: 029_instruction_recommendations
Create Date: 2026-04-30 00:01:00.000000

Adds a unique constraint on ``(essay_id, version_number)`` in the
``essay_versions`` table so that the database enforces version-number
uniqueness per essay.  The backing index is created concurrently to avoid
a full-table lock on the existing data.

The ``resubmit_essay`` service function uses ``SELECT … FOR UPDATE`` on the
parent ``Essay`` row to serialise concurrent resubmissions and prevent two
requests from computing the same ``max(version_number) + 1``.  This
constraint acts as a last-resort safety net if the row lock is somehow
bypassed (e.g., a Celery task or a future code path that skips the lock),
and will surface as a 409 ``ConflictError`` rather than a silent duplicate.

Zero-downtime: ``CREATE UNIQUE INDEX CONCURRENTLY`` builds the index without
holding a table-level lock; the constraint is then attached from the index
instantly via ``ALTER TABLE … ADD CONSTRAINT … USING INDEX``.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "030_ev_unique_version_number"
down_revision: str | None = "029_instruction_recommendations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# CREATE/DROP INDEX CONCURRENTLY cannot run inside a transaction block.
# This migration relies on op.get_context().autocommit_block() around those
# statements rather than a per-migration transaction override.
# (env.py always uses transaction_per_migration=True; a module-level variable
# would not be read by it.)

_INDEX_NAME = "ix_uq_essay_versions_essay_id_version_number"
_CONSTRAINT_NAME = "uq_essay_versions_essay_id_version_number"
_TABLE = "essay_versions"


def upgrade() -> None:
    # Build the unique index concurrently so the table is not locked.
    # autocommit_block() ensures the statement runs outside any transaction,
    # which is required by PostgreSQL for CONCURRENTLY index operations.
    with op.get_context().autocommit_block():
        op.execute(
            sa.text(
                f"CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS {_INDEX_NAME} "
                f"ON {_TABLE} (essay_id, version_number)"
            )
        )
    # Attach the constraint to the pre-built index (instant, no lock).
    # ALTER TABLE ... ADD CONSTRAINT ... USING INDEX is the correct DDL form;
    # SQLAlchemy's create_unique_constraint does not support postgresql_using_index.
    op.execute(
        sa.text(
            f"ALTER TABLE {_TABLE} ADD CONSTRAINT {_CONSTRAINT_NAME} "
            f"UNIQUE USING INDEX {_INDEX_NAME}"
        )
    )


def downgrade() -> None:
    op.drop_constraint(_CONSTRAINT_NAME, _TABLE, type_="unique")
    with op.get_context().autocommit_block():
        op.execute(sa.text(f"DROP INDEX CONCURRENTLY IF EXISTS {_INDEX_NAME}"))
