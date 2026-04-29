"""student_groups: add stability column

Revision ID: 027_student_groups_add_stability
Revises: 026_student_groups
Create Date: 2026-04-29 00:00:00.000000

Adds a ``stability`` column to ``student_groups`` to track whether each
skill-gap group is newly formed ('new'), has persisted across multiple
auto-grouping computations ('persistent'), or previously existed but no
longer meets the minimum size threshold ('exited').

Column design:
  - ``stability``  VARCHAR(20), NOT NULL, default 'new'.
                   One of: 'new', 'persistent', 'exited'.
                   Populated by the auto-grouping Celery task (M6-01) and
                   exposed by the class groups API (M6-02).

Downgrade:
  Drops the ``stability`` column, restoring the table to its pre-M6-02 shape.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "027_student_groups_add_stability"
down_revision: str | None = "026_student_groups"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "student_groups",
        sa.Column(
            "stability",
            sa.String(20),
            nullable=False,
            server_default="new",
        ),
    )


def downgrade() -> None:
    op.drop_column("student_groups", "stability")
