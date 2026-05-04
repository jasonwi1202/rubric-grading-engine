"""integrity_report: add unique constraint (essay_version_id, provider)

Revision ID: 015_integrity_report_unique_version_provider
Revises: 014_essay_embedding
Create Date: 2026-04-23 02:00:00.000000

Adds a unique constraint on ``(essay_version_id, provider)`` so that at most
one integrity report can exist per (version, provider) pair.  This makes the
``OriginalityAiProvider`` idempotency guard race-safe: a concurrent duplicate
insert is rejected at the DB level (``ON CONFLICT DO NOTHING``) rather than
creating a second row.

Zero-downtime: ``CREATE UNIQUE INDEX CONCURRENTLY`` builds the index without
holding a table-level lock; the constraint is then attached from the index.
The concurrent index operation is wrapped in ``op.get_context().autocommit_block()``
so it runs outside PostgreSQL's transaction scope (required for CONCURRENTLY).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "015_ir_unique_version_provider"
down_revision: str | None = "014_essay_embedding"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEX_NAME = "ix_uq_integrity_reports_version_provider"
_CONSTRAINT_NAME = "uq_integrity_reports_version_provider"
_TABLE = "integrity_reports"


def upgrade() -> None:
    # Build the unique index concurrently so the table is not locked.
    # autocommit_block() ensures the statement runs outside any transaction,
    # which is required by PostgreSQL for CONCURRENTLY index operations.
    with op.get_context().autocommit_block():
        op.execute(
            sa.text(
                f"CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS {_INDEX_NAME} "
                f"ON {_TABLE} (essay_version_id, provider)"
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
    # Dropping the constraint also drops the backing index (PostgreSQL
    # automatically drops an index that was attached to a constraint via
    # USING INDEX).  The subsequent DROP INDEX is therefore a no-op, but
    # the IF EXISTS guard makes it safe to re-run and documents intent.
    op.drop_constraint(_CONSTRAINT_NAME, _TABLE, type_="unique")
    with op.get_context().autocommit_block():
        op.execute(sa.text(f"DROP INDEX CONCURRENTLY IF EXISTS {_INDEX_NAME}"))
