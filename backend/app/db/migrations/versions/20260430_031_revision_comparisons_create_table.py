"""revision_comparisons: create table for M6-11 resubmission comparison data

Revision ID: 031_revision_comparisons_create_table
Revises: 030_essay_versions_unique_version_number
Create Date: 2026-04-30 12:00:00.000000

Creates the ``revision_comparisons`` table that stores criterion-level score
deltas, the low-effort revision flag, and optional LLM-based feedback-addressed
analysis for resubmitted essays (M6-11).

Table design:
  - ``essay_id``              UUID FK → essays(id) ON DELETE CASCADE, indexed.
                              Scope anchor for tenant-isolated reads.
  - ``base_version_id``       UUID FK → essay_versions(id) ON DELETE CASCADE.
                              The previous (base) essay version.
  - ``revised_version_id``    UUID FK → essay_versions(id) ON DELETE CASCADE.
                              The newly graded revision.
  - ``base_grade_id``         UUID FK → grades(id) ON DELETE CASCADE.
                              Grade record for the base version.
  - ``revised_grade_id``      UUID FK → grades(id) ON DELETE CASCADE.
                              Grade record for the revised version.
  - ``total_score_delta``     NUMERIC(6,2), NOT NULL.
                              revised.total_score − base.total_score.
  - ``criterion_deltas``      JSONB, NOT NULL.
                              [{criterion_id, base_score, revised_score, delta}]
  - ``is_low_effort``         BOOLEAN, NOT NULL, default FALSE.
                              True when heuristics flag a surface-level revision.
  - ``low_effort_reasons``    JSONB, NOT NULL, default '[]'.
                              Human-readable reason strings.
  - ``feedback_addressed``    JSONB, NULL.
                              LLM output: [{criterion_id, feedback_given,
                              addressed, detail}].  NULL until LLM analysis
                              completes or when LLM step is unavailable.
  - ``created_at``            TIMESTAMPTZ, NOT NULL, default now().

No RLS is applied to this table because the ``essay_id`` FK chain already
routes through the RLS-protected ``essays`` table; service-layer queries
always join through ``essays`` and enforce ``teacher_id`` in the WHERE clause.

Zero-downtime: ``CREATE INDEX CONCURRENTLY`` builds the ``essay_id`` index
without holding a table-level lock, wrapped in ``autocommit_block()`` as
required for CONCURRENTLY index operations.

Downgrade: drop index concurrently, then drop table.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "031_revision_comparisons_create_table"
down_revision: str | None = "030_essay_versions_unique_version_number"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# CREATE INDEX CONCURRENTLY requires autocommit mode.
transaction_per_migration = False

_TABLE = "revision_comparisons"
_INDEX_ESSAY_ID = "ix_revision_comparisons_essay_id"
_INDEX_REVISED = "ix_revision_comparisons_revised_version_id"


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. Create the revision_comparisons table.
    # ------------------------------------------------------------------
    op.create_table(
        _TABLE,
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "essay_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("essays.id", ondelete="CASCADE", name="fk_revision_comparisons_essays"),
            nullable=False,
        ),
        sa.Column(
            "base_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "essay_versions.id",
                ondelete="CASCADE",
                name="fk_revision_comparisons_base_version",
            ),
            nullable=False,
        ),
        sa.Column(
            "revised_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "essay_versions.id",
                ondelete="CASCADE",
                name="fk_revision_comparisons_revised_version",
            ),
            nullable=False,
        ),
        sa.Column(
            "base_grade_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "grades.id",
                ondelete="CASCADE",
                name="fk_revision_comparisons_base_grade",
            ),
            nullable=False,
        ),
        sa.Column(
            "revised_grade_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "grades.id",
                ondelete="CASCADE",
                name="fk_revision_comparisons_revised_grade",
            ),
            nullable=False,
        ),
        sa.Column(
            "total_score_delta",
            sa.Numeric(6, 2),
            nullable=False,
        ),
        sa.Column(
            "criterion_deltas",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "is_low_effort",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("FALSE"),
        ),
        sa.Column(
            "low_effort_reasons",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "feedback_addressed",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # ------------------------------------------------------------------
    # 2. Indexes — essay_id for tenant-scoped reads; revised_version_id
    #    for look-ups from the grading service (post-grading insert).
    #    Built concurrently to avoid table locks.
    # ------------------------------------------------------------------
    with op.get_context().autocommit_block():
        op.create_index(
            _INDEX_ESSAY_ID,
            _TABLE,
            ["essay_id"],
            postgresql_concurrently=True,
        )
        op.create_index(
            _INDEX_REVISED,
            _TABLE,
            ["revised_version_id"],
            postgresql_concurrently=True,
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.drop_index(_INDEX_REVISED, table_name=_TABLE, postgresql_concurrently=True)
        op.drop_index(_INDEX_ESSAY_ID, table_name=_TABLE, postgresql_concurrently=True)
    op.drop_table(_TABLE)
