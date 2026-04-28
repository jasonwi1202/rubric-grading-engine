"""essay_versions: add writing_snapshots JSONB column

Revision ID: 024_essay_versions_writing_snapshots
Revises: 023_students_teacher_notes
Create Date: 2026-04-28 00:00:00.000000

Adds a ``writing_snapshots`` JSONB column to ``essay_versions`` to support the
in-browser essay composition feature (M5-09).

Column design:
  - ``writing_snapshots``  JSONB, nullable.
                            NULL for essays ingested via file upload (no process
                            data captured).  For browser-composed essays, stores
                            an ordered array of snapshot objects:
                            [
                              {
                                "seq":          int,     sequence number (1-based)
                                "ts":           str,     ISO-8601 UTC timestamp
                                "word_count":   int,     word count at save time
                                "html_content": str      raw HTML from editor
                              },
                              ...
                            ]
                            The ``content`` column on the same row always holds
                            the plain-text equivalent of the latest snapshot's
                            ``html_content`` (HTML tags stripped).

Downgrade:
  Drops the column.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "024_essay_versions_writing_snapshots"
down_revision: str | None = "023_students_teacher_notes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "essay_versions",
        sa.Column(
            "writing_snapshots",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment=(
                "Ordered array of writing-process snapshots for browser-composed "
                "essays. NULL for file-upload essays. Each element: "
                "{seq, ts, word_count, html_content}."
            ),
        ),
    )


def downgrade() -> None:
    op.drop_column("essay_versions", "writing_snapshots")
