"""intervention_recommendations: create table with RLS tenant isolation

Revision ID: 033_intervention_recommendations
Revises: 032_validate_audit_logs_users_fk
Create Date: 2026-05-01 12:00:00.000000

Creates ``intervention_recommendations`` — the persistence target for
agent-generated intervention recommendations produced by the scheduled
intervention scan Celery task (M7-01).

Table design:
  - ``teacher_id``        UUID FK → users(id) ON DELETE CASCADE, indexed.
                           Stored directly so the RLS policy uses a single
                           equality check (matching the pattern used by all
                           other tenant-scoped tables).
  - ``student_id``        UUID FK → students(id) ON DELETE CASCADE, indexed.
                           The student whose skill profile triggered the signal.
  - ``trigger_type``      VARCHAR(30), NOT NULL.
                           One of: 'regression', 'persistent_gap', 'non_responder'.
  - ``skill_key``         VARCHAR(200), NULL.
                           Canonical skill dimension key; NULL for student-level
                           signals (e.g. 'non_responder').
  - ``urgency``           INTEGER, NOT NULL. 1–4; 4 = most urgent.
  - ``trigger_reason``    TEXT, NOT NULL.
                           Human-readable sentence explaining why this was triggered.
  - ``evidence_summary``  TEXT, NOT NULL.
                           Supporting data description (avg_score, trend, etc.).
  - ``suggested_action``  TEXT, NOT NULL. Concrete action for the teacher.
  - ``details``           JSONB, NOT NULL, default '{}'.
                           Signal-specific context (avg_score, trend, etc.).
  - ``status``            VARCHAR(20), NOT NULL, default 'pending_review'.
                           One of: 'pending_review', 'approved', 'dismissed'.
  - ``actioned_at``       TIMESTAMPTZ, NULL. Set when teacher approves/dismisses.
  - ``created_at``        TIMESTAMPTZ, NOT NULL, default now().

Partial unique index:
  A partial unique index on (teacher_id, student_id, trigger_type, skill_key)
  WHERE status = 'pending_review' prevents duplicate pending recommendations
  for the same signal from accumulating across scheduled runs.  Approved and
  dismissed rows are historical records and are not constrained.

RLS:
  Enables FORCE ROW LEVEL SECURITY and a 'tenant_isolation' PERMISSIVE policy
  matching the pattern used by all other tenant-scoped tables.

Zero-downtime:
  Two ``CREATE INDEX CONCURRENTLY`` calls build the ``teacher_id`` and
  ``student_id`` indexes without holding a table-level lock.  The partial
  unique index for idempotency is also created concurrently.  All concurrent
  index builds run inside ``autocommit_block()`` so PostgreSQL sees them
  outside a transaction.

Downgrade:
  Drops the policy, disables RLS, then drops the table (indexes are
  dropped automatically with the table).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "033_intervention_recommendations"
down_revision: str | None = "032_validate_audit_logs_users_fk"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# CREATE INDEX CONCURRENTLY cannot run inside a transaction block.
# Setting this to False tells Alembic to run this migration outside the
# default per-migration transaction so the concurrent index builds succeed.
transaction_per_migration = False


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. Create the intervention_recommendations table
    # ------------------------------------------------------------------
    op.create_table(
        "intervention_recommendations",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "teacher_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "users.id",
                ondelete="CASCADE",
                name="fk_intervention_recommendations_users",
            ),
            nullable=False,
        ),
        sa.Column(
            "student_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "students.id",
                ondelete="CASCADE",
                name="fk_intervention_recommendations_students",
            ),
            nullable=False,
        ),
        sa.Column("trigger_type", sa.String(30), nullable=False),
        sa.Column("skill_key", sa.String(200), nullable=True),
        sa.Column("urgency", sa.Integer(), nullable=False),
        sa.Column("trigger_reason", sa.Text(), nullable=False),
        sa.Column("evidence_summary", sa.Text(), nullable=False),
        sa.Column("suggested_action", sa.Text(), nullable=False),
        sa.Column(
            "details",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default=sa.text("'pending_review'"),
        ),
        sa.Column("actioned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # ------------------------------------------------------------------
    # 2. Indexes
    #    - teacher_id and student_id for fast tenant-scoped reads.
    #    - Partial unique index on (teacher_id, student_id, trigger_type,
    #      skill_key) WHERE status = 'pending_review' for idempotency.
    #    All created concurrently (no table lock).
    # ------------------------------------------------------------------
    with op.get_context().autocommit_block():
        op.create_index(
            "ix_intervention_recommendations_teacher_id",
            "intervention_recommendations",
            ["teacher_id"],
            postgresql_concurrently=True,
        )
        op.create_index(
            "ix_intervention_recommendations_student_id",
            "intervention_recommendations",
            ["student_id"],
            postgresql_concurrently=True,
        )
        op.create_index(
            "uq_intervention_pending_signal",
            "intervention_recommendations",
            ["teacher_id", "student_id", "trigger_type", "skill_key"],
            unique=True,
            postgresql_where=sa.text("status = 'pending_review'"),
            postgresql_concurrently=True,
        )

    # ------------------------------------------------------------------
    # 3. Enable RLS — FORCE so the policy applies to the table owner too
    # ------------------------------------------------------------------
    op.execute(sa.text("ALTER TABLE intervention_recommendations ENABLE ROW LEVEL SECURITY"))
    op.execute(sa.text("ALTER TABLE intervention_recommendations FORCE ROW LEVEL SECURITY"))
    op.execute(
        sa.text("""
        CREATE POLICY tenant_isolation ON intervention_recommendations
        FOR ALL
        USING (
            teacher_id = NULLIF(current_setting('app.current_teacher_id', true), '')::uuid
        )
    """)
    )


def downgrade() -> None:
    op.execute(sa.text("DROP POLICY IF EXISTS tenant_isolation ON intervention_recommendations"))
    op.execute(sa.text("ALTER TABLE intervention_recommendations NO FORCE ROW LEVEL SECURITY"))
    op.execute(sa.text("ALTER TABLE intervention_recommendations DISABLE ROW LEVEL SECURITY"))

    with op.get_context().autocommit_block():
        op.drop_index(
            "uq_intervention_pending_signal",
            table_name="intervention_recommendations",
            postgresql_concurrently=True,
        )
        op.drop_index(
            "ix_intervention_recommendations_student_id",
            table_name="intervention_recommendations",
            postgresql_concurrently=True,
        )
        op.drop_index(
            "ix_intervention_recommendations_teacher_id",
            table_name="intervention_recommendations",
            postgresql_concurrently=True,
        )
    op.drop_table("intervention_recommendations")
