"""student_groups: create table with RLS tenant isolation

Revision ID: 026_student_groups
Revises: 025_essay_versions_signals
Create Date: 2026-04-29 00:00:00.000000

Creates ``student_groups`` — the persistence target for the auto-grouping
Celery task (M6-01).  One row per (teacher_id, class_id, skill_key) triplet
stores the set of students who share an underperforming skill dimension within
a class.

Table design:
  - ``teacher_id``      UUID FK → users(id) ON DELETE CASCADE, indexed.
                        Stored directly so the RLS policy can use a single
                        equality check (same pattern as student_skill_profiles,
                        students, classes, etc.).
  - ``class_id``        UUID FK → classes(id) ON DELETE CASCADE, indexed.
  - ``skill_key``       VARCHAR(200), NOT NULL.
                        Canonical skill dimension key (e.g. "evidence").
  - ``label``           VARCHAR(200), NOT NULL.
                        Human-readable label derived from skill_key.
  - ``student_ids``     JSONB, NOT NULL, default '[]'.
                        Array of student UUID strings sharing this gap.
  - ``student_count``   INTEGER, NOT NULL, default 0.
                        Denormalised count of student_ids for fast queries.
  - ``computed_at``     TIMESTAMPTZ, NOT NULL, server default now().
                        Timestamp of the most recent group computation.
  - Unique constraint on (teacher_id, class_id, skill_key): one row per class
    per skill dimension, enabling idempotent upserts.

RLS:
  Enables FORCE ROW LEVEL SECURITY and a "tenant_isolation" PERMISSIVE policy
  matching the pattern used by all other tenant-scoped tables.

Downgrade:
  Drops the policy, disables RLS, then drops the table.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "026_student_groups"
down_revision: str | None = "025_essay_versions_signals"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. Create the student_groups table
    # ------------------------------------------------------------------
    op.create_table(
        "student_groups",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "teacher_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE", name="fk_student_groups_users"),
            nullable=False,
        ),
        sa.Column(
            "class_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("classes.id", ondelete="CASCADE", name="fk_student_groups_classes"),
            nullable=False,
        ),
        sa.Column(
            "skill_key",
            sa.String(200),
            nullable=False,
        ),
        sa.Column(
            "label",
            sa.String(200),
            nullable=False,
        ),
        sa.Column(
            "student_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "student_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "teacher_id",
            "class_id",
            "skill_key",
            name="uq_student_groups_class_skill",
        ),
    )

    # ------------------------------------------------------------------
    # 2. Indexes
    # ------------------------------------------------------------------
    op.create_index(
        "ix_student_groups_teacher_id",
        "student_groups",
        ["teacher_id"],
    )
    op.create_index(
        "ix_student_groups_class_id",
        "student_groups",
        ["class_id"],
    )

    # ------------------------------------------------------------------
    # 3. Enable RLS
    # ------------------------------------------------------------------
    op.execute(sa.text("ALTER TABLE student_groups ENABLE ROW LEVEL SECURITY"))
    op.execute(sa.text("ALTER TABLE student_groups FORCE ROW LEVEL SECURITY"))
    op.execute(
        sa.text("""
        CREATE POLICY tenant_isolation ON student_groups
        FOR ALL
        USING (
            teacher_id = NULLIF(current_setting('app.current_teacher_id', true), '')::uuid
        )
    """)
    )


def downgrade() -> None:
    op.execute(sa.text("DROP POLICY IF EXISTS tenant_isolation ON student_groups"))
    op.execute(sa.text("ALTER TABLE student_groups NO FORCE ROW LEVEL SECURITY"))
    op.execute(sa.text("ALTER TABLE student_groups DISABLE ROW LEVEL SECURITY"))

    op.drop_index("ix_student_groups_class_id", table_name="student_groups")
    op.drop_index("ix_student_groups_teacher_id", table_name="student_groups")
    op.drop_table("student_groups")
