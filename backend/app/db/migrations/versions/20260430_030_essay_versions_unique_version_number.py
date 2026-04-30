"""essay_versions: add unique constraint on (essay_id, version_number)

Revision ID: 030_essay_versions_unique_version_number
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
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "030_essay_versions_unique_version_number"
down_revision: str | None = "029_instruction_recommendations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEX_NAME = "uq_essay_versions_essay_id_version_number"
_CONSTRAINT_NAME = "uq_essay_versions_essay_id_version_number"


def upgrade() -> None:
    # Create the supporting index concurrently (no table lock on existing rows).
    op.create_index(
        _INDEX_NAME,
        "essay_versions",
        ["essay_id", "version_number"],
        unique=True,
        postgresql_concurrently=True,
    )
    # Attach the unique constraint backed by the index just created.
    op.create_unique_constraint(
        _CONSTRAINT_NAME,
        "essay_versions",
        ["essay_id", "version_number"],
    )


def downgrade() -> None:
    op.drop_constraint(_CONSTRAINT_NAME, "essay_versions", type_="unique")
    op.drop_index(_INDEX_NAME, table_name="essay_versions")
