"""essay_versions: add process_signals JSONB column

Revision ID: 025_essay_versions_signals
Revises: 024_essay_versions_snapshots
Create Date: 2026-04-28 00:00:00.000000

Adds a ``process_signals`` JSONB column to ``essay_versions`` to support the
composition timeline feature (M5-10).

Column design:
  - ``process_signals``  JSONB, nullable.
                         NULL until the teacher first requests process signals
                         for the essay (lazy computation).  Once computed, stores
                         a dict with the full composition timeline analysis so
                         subsequent requests return the cached result without
                         re-running the analysis.

                         Schema:
                         {
                           "snapshot_count":            int,
                           "computed_at":               str  (ISO-8601),
                           "has_process_data":          bool,
                           "session_count":             int,
                           "active_writing_seconds":    float,
                           "total_elapsed_seconds":     float,
                           "inter_session_gaps_seconds": [float, ...],
                           "sessions": [
                             {
                               "session_index":   int,
                               "started_at":      str,
                               "ended_at":        str,
                               "duration_seconds": float,
                               "snapshot_count":  int,
                               "word_count_start": int,
                               "word_count_end":  int,
                               "words_added":     int
                             },
                             ...
                           ],
                           "paste_events": [
                             {
                               "snapshot_seq":  int,
                               "occurred_at":   str,
                               "words_before":  int,
                               "words_after":   int,
                               "words_added":   int,
                               "session_index": int
                             },
                             ...
                           ],
                           "rapid_completion_events": [
                             {
                               "session_index":      int,
                               "duration_seconds":   float,
                               "words_at_start":     int,
                               "words_at_end":       int,
                               "completion_fraction": float
                             },
                             ...
                           ]
                         }

                         Cache invalidation: the service layer compares
                         ``snapshot_count`` in the cached payload with the
                         current length of ``writing_snapshots`` and
                         recomputes when they differ.

Downgrade:
  Drops the column.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "025_essay_versions_signals"
down_revision: str | None = "024_essay_versions_snapshots"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "essay_versions",
        sa.Column(
            "process_signals",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment=(
                "Cached composition timeline signals (M5-10). NULL until first "
                "requested. Re-computed when snapshot_count in cache differs from "
                "len(writing_snapshots). Keys: snapshot_count, computed_at, "
                "has_process_data, session_count, active_writing_seconds, "
                "total_elapsed_seconds, inter_session_gaps_seconds, sessions, "
                "paste_events, rapid_completion_events."
            ),
        ),
    )


def downgrade() -> None:
    op.drop_column("essay_versions", "process_signals")
