"""instruction_recommendations: create table with RLS tenant isolation

Revision ID: 029_instruction_recommendations
Revises: 028_teacher_worklist_items
Create Date: 2026-04-30 00:00:00.000000

Creates ``instruction_recommendations`` — the persistence target for AI-
generated instruction recommendations produced from student skill profiles or
class skill-gap groups (M6-07).

Table design:
  - ``teacher_id``        UUID FK → users(id) ON DELETE CASCADE, indexed.
                           Stored directly so the RLS policy uses a single
                           equality check (same pattern as all tenant-scoped
                           tables).
  - ``student_id``        UUID FK → students(id) ON DELETE CASCADE, nullable.
                           Populated for student-level recommendations.
  - ``group_id``          UUID FK → student_groups(id) ON DELETE CASCADE,
                           nullable.  Populated for group-level recommendations.
  - ``worklist_item_id``  UUID FK → teacher_worklist_items(id) ON DELETE SET
                           NULL, nullable.  Populated when generation was
                           triggered from a worklist item.
  - ``skill_key``         VARCHAR(200), nullable.  Target skill dimension; NULL
                           when targeting all detected gaps.
  - ``grade_level``       VARCHAR(100), NOT NULL.  Grade-level descriptor used
                           in the prompt (e.g. 'Grade 8').
  - ``prompt_version``    VARCHAR(50), NOT NULL.  Prompt module version.
  - ``recommendations``   JSONB, NOT NULL, default '[]'.  Validated array of
                           recommendation objects.
  - ``evidence_summary``  TEXT, NOT NULL.  Human-readable description of the
                           skill gaps that triggered generation.
  - ``status``            VARCHAR(20), NOT NULL, default 'pending_review'.
                           One of: 'pending_review', 'accepted', 'dismissed'.
  - ``created_at``        TIMESTAMPTZ, NOT NULL, default now().

RLS:
  Enables FORCE ROW LEVEL SECURITY and a 'tenant_isolation' PERMISSIVE
  policy matching the pattern used by all other tenant-scoped tables.

Zero-downtime:
  Three ``CREATE INDEX CONCURRENTLY`` calls build the ``teacher_id``,
  ``student_id``, and ``group_id`` indexes without holding a table-level
  lock.  Each runs inside ``autocommit_block()`` so PostgreSQL sees them
  outside a transaction, which is required for ``CONCURRENTLY`` index
  builds.  Alembic's per-migration transaction is therefore disabled via
  ``transaction_per_migration = False``.

Downgrade:
  Drops the policy, disables RLS, then drops the table (indexes are
  dropped automatically with the table).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "029_instruction_recommendations"
down_revision: str | None = "028_teacher_worklist_items"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# CREATE INDEX CONCURRENTLY cannot run inside a transaction block.
transaction_per_migration = False


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. Create the instruction_recommendations table
    # ------------------------------------------------------------------
    op.create_table(
        "instruction_recommendations",
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
                name="fk_instruction_recommendations_users",
            ),
            nullable=False,
        ),
        sa.Column(
            "student_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "students.id",
                ondelete="CASCADE",
                name="fk_instruction_recommendations_students",
            ),
            nullable=True,
        ),
        sa.Column(
            "group_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "student_groups.id",
                ondelete="CASCADE",
                name="fk_instruction_recommendations_student_groups",
            ),
            nullable=True,
        ),
        sa.Column(
            "worklist_item_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "teacher_worklist_items.id",
                ondelete="SET NULL",
                name="fk_instruction_recommendations_worklist_items",
            ),
            nullable=True,
        ),
        sa.Column("skill_key", sa.String(200), nullable=True),
        sa.Column("grade_level", sa.String(100), nullable=False),
        sa.Column("prompt_version", sa.String(50), nullable=False),
        sa.Column(
            "recommendations",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("evidence_summary", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default=sa.text("'pending_review'"),
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
    #    locked during the migration.
    # ------------------------------------------------------------------
    with op.get_context().autocommit_block():
        op.create_index(
            "ix_instruction_recommendations_teacher_id",
            "instruction_recommendations",
            ["teacher_id"],
            postgresql_concurrently=True,
        )
        op.create_index(
            "ix_instruction_recommendations_student_id",
            "instruction_recommendations",
            ["student_id"],
            postgresql_concurrently=True,
        )
        op.create_index(
            "ix_instruction_recommendations_group_id",
            "instruction_recommendations",
            ["group_id"],
            postgresql_concurrently=True,
        )

    # ------------------------------------------------------------------
    # 3. Enable RLS — FORCE so the policy applies to the table owner too
    # ------------------------------------------------------------------
    op.execute(
        sa.text("ALTER TABLE instruction_recommendations ENABLE ROW LEVEL SECURITY")
    )
    op.execute(
        sa.text("ALTER TABLE instruction_recommendations FORCE ROW LEVEL SECURITY")
    )
    op.execute(
        sa.text("""
        CREATE POLICY tenant_isolation ON instruction_recommendations
        FOR ALL
        USING (
            teacher_id = NULLIF(current_setting('app.current_teacher_id', true), '')::uuid
        )
    """)
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "DROP POLICY IF EXISTS tenant_isolation ON instruction_recommendations"
        )
    )
    op.execute(
        sa.text(
            "ALTER TABLE instruction_recommendations NO FORCE ROW LEVEL SECURITY"
        )
    )
    op.execute(
        sa.text(
            "ALTER TABLE instruction_recommendations DISABLE ROW LEVEL SECURITY"
        )
    )

    with op.get_context().autocommit_block():
        op.drop_index(
            "ix_instruction_recommendations_group_id",
            table_name="instruction_recommendations",
            postgresql_concurrently=True,
        )
        op.drop_index(
            "ix_instruction_recommendations_student_id",
            table_name="instruction_recommendations",
            postgresql_concurrently=True,
        )
        op.drop_index(
            "ix_instruction_recommendations_teacher_id",
            table_name="instruction_recommendations",
            postgresql_concurrently=True,
        )
    op.drop_table("instruction_recommendations")
