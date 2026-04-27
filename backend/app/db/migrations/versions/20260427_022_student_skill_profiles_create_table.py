"""student_skill_profiles: create table with RLS tenant isolation

Revision ID: 022_student_skill_profiles
Revises: 021_grades_prompt_version
Create Date: 2026-04-27 00:00:00.000000

Creates ``student_skill_profiles`` — a persistent, per-student aggregation of
normalized skill scores across all graded assignments.

Table design:
  - ``teacher_id``        UUID FK → users(id) ON DELETE CASCADE, indexed.
                          Stored directly on this table so the RLS policy can
                          use a single equality check (same pattern as students,
                          classes, etc.) rather than a multi-hop sub-query.
  - ``student_id``        UUID FK → students(id) ON DELETE CASCADE, indexed.
  - Unique constraint on (teacher_id, student_id): one profile per student.
  - ``skill_scores``      JSONB, NOT NULL, default '{}'.
                          Shape: {skill_name: {avg_score, trend, data_points,
                          last_updated}}.  Skill names are canonical dimension
                          names produced by the skill-normalization layer (M5-01).
  - ``assignment_count``  INTEGER, NOT NULL, default 0.
                          Counts graded assignments whose scores contributed.
  - ``last_updated_at``   TIMESTAMPTZ, NOT NULL, server default now().
  - ``created_at``        TIMESTAMPTZ, NOT NULL, server default now().

RLS:
  Enables FORCE ROW LEVEL SECURITY and a "tenant_isolation" PERMISSIVE policy
  that checks teacher_id = NULLIF(current_setting('app.current_teacher_id',
  true), '')::uuid, matching the pattern of all other tenant-scoped tables.

Downgrade:
  Drops the policy, disables RLS, then drops the table.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "022_student_skill_profiles"
down_revision: str | None = "021_grades_prompt_version"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. Create the student_skill_profiles table
    # ------------------------------------------------------------------
    op.create_table(
        "student_skill_profiles",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "teacher_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE", name="fk_student_skill_profiles_users"),
            nullable=False,
        ),
        sa.Column(
            "student_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("students.id", ondelete="CASCADE", name="fk_student_skill_profiles_students"),
            nullable=False,
        ),
        sa.Column(
            "skill_scores",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "assignment_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "last_updated_at",
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
        sa.UniqueConstraint(
            "teacher_id",
            "student_id",
            name="uq_skill_profile_teacher_student",
        ),
    )

    # ------------------------------------------------------------------
    # 2. Indexes — teacher_id and student_id for fast tenant-scoped reads
    # ------------------------------------------------------------------
    op.create_index(
        "ix_student_skill_profiles_teacher_id",
        "student_skill_profiles",
        ["teacher_id"],
    )
    op.create_index(
        "ix_student_skill_profiles_student_id",
        "student_skill_profiles",
        ["student_id"],
    )

    # ------------------------------------------------------------------
    # 3. Enable RLS — FORCE so the policy applies to the table owner too
    # ------------------------------------------------------------------
    op.execute(sa.text("ALTER TABLE student_skill_profiles ENABLE ROW LEVEL SECURITY"))
    op.execute(sa.text("ALTER TABLE student_skill_profiles FORCE ROW LEVEL SECURITY"))
    op.execute(
        sa.text("""
        CREATE POLICY tenant_isolation ON student_skill_profiles
        FOR ALL
        USING (
            teacher_id = NULLIF(current_setting('app.current_teacher_id', true), '')::uuid
        )
    """)
    )


def downgrade() -> None:
    # Drop the RLS policy and disable RLS before dropping the table.
    op.execute(
        sa.text("DROP POLICY IF EXISTS tenant_isolation ON student_skill_profiles")
    )
    op.execute(sa.text("ALTER TABLE student_skill_profiles NO FORCE ROW LEVEL SECURITY"))
    op.execute(sa.text("ALTER TABLE student_skill_profiles DISABLE ROW LEVEL SECURITY"))

    op.drop_index("ix_student_skill_profiles_student_id", table_name="student_skill_profiles")
    op.drop_index("ix_student_skill_profiles_teacher_id", table_name="student_skill_profiles")
    op.drop_table("student_skill_profiles")
