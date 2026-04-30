"""teacher_worklist_items: create table with RLS tenant isolation

Revision ID: 028_teacher_worklist_items
Revises: 027_student_groups_add_stability
Create Date: 2026-04-29 00:00:00.000000

Creates ``teacher_worklist_items`` — the persistence target for the
worklist generation Celery task (M6-04).  One row per actionable student
signal surfaced to the teacher.

Table design:
  - ``teacher_id``       UUID FK → users(id) ON DELETE CASCADE, indexed.
                          Stored directly so the RLS policy uses a single
                          equality check (same pattern as all tenant-scoped
                          tables).
  - ``student_id``       UUID FK → students(id) ON DELETE CASCADE, indexed.
  - ``trigger_type``     VARCHAR(30), NOT NULL.
                          One of: 'persistent_gap', 'regression',
                          'high_inconsistency', 'non_responder'.
  - ``skill_key``        VARCHAR(200), NULL.
                          Canonical skill dimension key; NULL for
                          student-level triggers like non_responder.
  - ``urgency``          INTEGER, NOT NULL. 1–4; 4 = most urgent.
  - ``suggested_action`` TEXT, NOT NULL.  Concrete action for the teacher.
  - ``details``          JSONB, NOT NULL, default '{}'.  Signal-specific
                          context (std_dev, avg_score, improvement, etc.).
  - ``status``           VARCHAR(20), NOT NULL, default 'active'.
                          One of: 'active', 'snoozed', 'completed', 'dismissed'.
  - ``snoozed_until``    TIMESTAMPTZ, NULL.  Set when status = 'snoozed'.
  - ``completed_at``     TIMESTAMPTZ, NULL.  Set when status = 'completed'.
  - ``generated_at``     TIMESTAMPTZ, NOT NULL.  Worklist computation time.
  - ``created_at``       TIMESTAMPTZ, NOT NULL, default now().

RLS:
  Enables FORCE ROW LEVEL SECURITY and a "tenant_isolation" PERMISSIVE
  policy matching the pattern used by all other tenant-scoped tables.

Zero-downtime: Two ``CREATE INDEX CONCURRENTLY`` calls build the
  ``teacher_id`` and ``student_id`` indexes without holding a table-level
  lock.  Each runs inside ``autocommit_block()`` so PostgreSQL sees them
  outside a transaction, which is required for ``CONCURRENTLY`` index
  builds.  Alembic's per-migration transaction is therefore disabled via
  ``transaction_per_migration = False``.

Downgrade:
  Drops the policy, disables RLS, then drops the table.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "028_teacher_worklist_items"
down_revision: str | None = "027_student_groups_add_stability"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# CREATE INDEX CONCURRENTLY cannot run inside a transaction block.
# Setting this to False tells Alembic to run this migration outside the
# default per-migration transaction so the concurrent index builds succeed.
transaction_per_migration = False


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. Create the teacher_worklist_items table
    # ------------------------------------------------------------------
    op.create_table(
        "teacher_worklist_items",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "teacher_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE", name="fk_teacher_worklist_items_users"),
            nullable=False,
        ),
        sa.Column(
            "student_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "students.id", ondelete="CASCADE", name="fk_teacher_worklist_items_students"
            ),
            nullable=False,
        ),
        sa.Column(
            "trigger_type",
            sa.String(30),
            nullable=False,
        ),
        sa.Column(
            "skill_key",
            sa.String(200),
            nullable=True,
        ),
        sa.Column(
            "urgency",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "suggested_action",
            sa.Text(),
            nullable=False,
        ),
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
            server_default=sa.text("'active'"),
        ),
        sa.Column(
            "snoozed_until",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "completed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "generated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # ------------------------------------------------------------------
    # 2. Indexes — teacher_id and student_id for fast tenant-scoped reads.
    #    Created concurrently outside a transaction so the table is not
    #    locked during the migration.  autocommit_block() is required by
    #    CREATE INDEX CONCURRENTLY.
    # ------------------------------------------------------------------
    with op.get_context().autocommit_block():
        op.create_index(
            "ix_teacher_worklist_items_teacher_id",
            "teacher_worklist_items",
            ["teacher_id"],
            postgresql_concurrently=True,
        )
        op.create_index(
            "ix_teacher_worklist_items_student_id",
            "teacher_worklist_items",
            ["student_id"],
            postgresql_concurrently=True,
        )

    # ------------------------------------------------------------------
    # 3. Enable RLS — FORCE so the policy applies to the table owner too
    # ------------------------------------------------------------------
    op.execute(sa.text("ALTER TABLE teacher_worklist_items ENABLE ROW LEVEL SECURITY"))
    op.execute(sa.text("ALTER TABLE teacher_worklist_items FORCE ROW LEVEL SECURITY"))
    op.execute(
        sa.text("""
        CREATE POLICY tenant_isolation ON teacher_worklist_items
        FOR ALL
        USING (
            teacher_id = NULLIF(current_setting('app.current_teacher_id', true), '')::uuid
        )
    """)
    )


def downgrade() -> None:
    op.execute(sa.text("DROP POLICY IF EXISTS tenant_isolation ON teacher_worklist_items"))
    op.execute(sa.text("ALTER TABLE teacher_worklist_items NO FORCE ROW LEVEL SECURITY"))
    op.execute(sa.text("ALTER TABLE teacher_worklist_items DISABLE ROW LEVEL SECURITY"))

    with op.get_context().autocommit_block():
        op.drop_index(
            "ix_teacher_worklist_items_student_id",
            table_name="teacher_worklist_items",
            postgresql_concurrently=True,
        )
        op.drop_index(
            "ix_teacher_worklist_items_teacher_id",
            table_name="teacher_worklist_items",
            postgresql_concurrently=True,
        )
    op.drop_table("teacher_worklist_items")
