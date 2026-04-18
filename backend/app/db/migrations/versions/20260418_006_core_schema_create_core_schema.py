"""create core schema: classes, students, rubrics, assignments, essays, grades

Revision ID: 006_core_schema
Revises: 005_users_onboarding
Create Date: 2026-04-18 00:00:00.000000

Creates the core grading-domain schema on top of the existing users and
audit_logs tables:

  - Enables the ``pgvector`` PostgreSQL extension (required for future
    embedding columns; harmless if not yet used).
  - Creates ENUM types: assignmentstatus, essaystatus, strictnesslevel,
    confidencelevel.
  - Tables (in dependency order):
      classes, students, class_enrollments,
      rubrics, rubric_criteria,
      assignments, essays, essay_versions,
      grades, criterion_scores
  - Adds a foreign key from ``audit_logs.teacher_id`` → ``users.id``
    (this FK was intentionally deferred until users existed and all
    dependent tables were in place).
  - Attaches an INSERT-only trigger to ``audit_logs`` so that UPDATE and
    DELETE statements raise a hard error at the database level.

All indexes on the new tables are created inside the same transaction as the
table creation (tables are empty, so CONCURRENTLY is not needed here).

Downgrade drops every artifact in reverse order.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "006_core_schema"
down_revision: str | None = "005_users_onboarding"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# ---------------------------------------------------------------------------
# Helpers — ENUM creation / removal
# ---------------------------------------------------------------------------

_ENUMS = [
    postgresql.ENUM(
        "draft",
        "open",
        "grading",
        "review",
        "complete",
        "returned",
        name="assignmentstatus",
    ),
    postgresql.ENUM(
        "unassigned",
        "queued",
        "grading",
        "graded",
        "reviewed",
        "locked",
        "returned",
        name="essaystatus",
    ),
    postgresql.ENUM(
        "lenient",
        "balanced",
        "strict",
        name="strictnesslevel",
    ),
    postgresql.ENUM(
        "high",
        "medium",
        "low",
        name="confidencelevel",
    ),
]


def _create_enums(bind: sa.engine.Connection) -> None:
    for enum_type in _ENUMS:
        enum_type.create(bind, checkfirst=True)


def _drop_enums(bind: sa.engine.Connection) -> None:
    for enum_type in reversed(_ENUMS):
        enum_type.drop(bind, checkfirst=True)


# ---------------------------------------------------------------------------
# upgrade
# ---------------------------------------------------------------------------


def upgrade() -> None:
    bind = op.get_bind()

    # ------------------------------------------------------------------
    # 1. pgvector extension
    # ------------------------------------------------------------------
    op.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))

    # ------------------------------------------------------------------
    # 2. ENUM types
    # ------------------------------------------------------------------
    _create_enums(bind)

    # ------------------------------------------------------------------
    # 3. classes
    # ------------------------------------------------------------------
    op.create_table(
        "classes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "teacher_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE", name="fk_classes_users"),
            nullable=False,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("subject", sa.String(100), nullable=False),
        sa.Column("grade_level", sa.String(20), nullable=False),
        sa.Column("academic_year", sa.String(10), nullable=False),
        sa.Column(
            "is_archived",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    # Composite index for the primary access pattern: list classes for a teacher
    # filtered by year and archive status.
    op.create_index(
        "ix_classes_teacher_id_academic_year_is_archived",
        "classes",
        ["teacher_id", "academic_year", "is_archived"],
    )

    # ------------------------------------------------------------------
    # 4. students
    # ------------------------------------------------------------------
    op.create_table(
        "students",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "teacher_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE", name="fk_students_users"),
            nullable=False,
        ),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column("external_id", sa.String(255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_students_teacher_id", "students", ["teacher_id"])

    # ------------------------------------------------------------------
    # 5. class_enrollments
    # ------------------------------------------------------------------
    op.create_table(
        "class_enrollments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "class_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("classes.id", ondelete="CASCADE", name="fk_class_enrollments_classes"),
            nullable=False,
        ),
        sa.Column(
            "student_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("students.id", ondelete="CASCADE", name="fk_class_enrollments_students"),
            nullable=False,
        ),
        sa.Column(
            "enrolled_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_class_enrollments_class_id", "class_enrollments", ["class_id"])
    op.create_index("ix_class_enrollments_student_id", "class_enrollments", ["student_id"])
    # Partial unique index: a student may only have one active enrollment per class.
    op.create_index(
        "ix_class_enrollments_active",
        "class_enrollments",
        ["class_id", "student_id"],
        unique=True,
        postgresql_where=sa.text("removed_at IS NULL"),
    )

    # ------------------------------------------------------------------
    # 6. rubrics
    # ------------------------------------------------------------------
    op.create_table(
        "rubrics",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "teacher_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE", name="fk_rubrics_users"),
            nullable=False,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "is_template",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_rubrics_teacher_id", "rubrics", ["teacher_id"])

    # ------------------------------------------------------------------
    # 7. rubric_criteria
    # ------------------------------------------------------------------
    op.create_table(
        "rubric_criteria",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "rubric_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("rubrics.id", ondelete="CASCADE", name="fk_rubric_criteria_rubrics"),
            nullable=False,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("weight", sa.Numeric(5, 2), nullable=False),
        sa.Column("min_score", sa.Integer(), nullable=False),
        sa.Column("max_score", sa.Integer(), nullable=False),
        sa.Column("display_order", sa.Integer(), nullable=False),
        sa.Column("anchor_descriptions", postgresql.JSONB(), nullable=True),
    )
    op.create_index("ix_rubric_criteria_rubric_id", "rubric_criteria", ["rubric_id"])

    # ------------------------------------------------------------------
    # 8. assignments
    # ------------------------------------------------------------------
    op.create_table(
        "assignments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "class_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("classes.id", ondelete="CASCADE", name="fk_assignments_classes"),
            nullable=False,
        ),
        sa.Column(
            "rubric_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("rubrics.id", ondelete="RESTRICT", name="fk_assignments_rubrics"),
            nullable=False,
        ),
        sa.Column("rubric_snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=True),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column(
            "status",
            postgresql.ENUM(
                "draft",
                "open",
                "grading",
                "review",
                "complete",
                "returned",
                name="assignmentstatus",
                create_type=False,
            ),
            nullable=False,
            server_default="draft",
        ),
        sa.Column(
            "resubmission_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("resubmission_limit", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_assignments_class_id", "assignments", ["class_id"])
    op.create_index("ix_assignments_rubric_id", "assignments", ["rubric_id"])

    # ------------------------------------------------------------------
    # 9. essays
    # ------------------------------------------------------------------
    op.create_table(
        "essays",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "assignment_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("assignments.id", ondelete="CASCADE", name="fk_essays_assignments"),
            nullable=False,
        ),
        sa.Column(
            "student_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("students.id", ondelete="SET NULL", name="fk_essays_students"),
            nullable=True,
        ),
        sa.Column(
            "status",
            postgresql.ENUM(
                "unassigned",
                "queued",
                "grading",
                "graded",
                "reviewed",
                "locked",
                "returned",
                name="essaystatus",
                create_type=False,
            ),
            nullable=False,
            server_default="unassigned",
        ),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_essays_assignment_id", "essays", ["assignment_id"])
    op.create_index("ix_essays_student_id", "essays", ["student_id"])
    # Partial unique index: one essay per student per assignment (unassigned
    # uploads are excluded so that multiple unassigned uploads can coexist).
    op.create_index(
        "ix_essays_assignment_id_student_id",
        "essays",
        ["assignment_id", "student_id"],
        unique=True,
        postgresql_where=sa.text("student_id IS NOT NULL"),
    )

    # ------------------------------------------------------------------
    # 10. essay_versions
    # ------------------------------------------------------------------
    op.create_table(
        "essay_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "essay_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("essays.id", ondelete="CASCADE", name="fk_essay_versions_essays"),
            nullable=False,
        ),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("file_storage_key", sa.String(500), nullable=True),
        sa.Column("word_count", sa.Integer(), nullable=False),
        sa.Column(
            "submitted_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_essay_versions_essay_id", "essay_versions", ["essay_id"])

    # ------------------------------------------------------------------
    # 11. grades
    # ------------------------------------------------------------------
    op.create_table(
        "grades",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "essay_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "essay_versions.id",
                ondelete="CASCADE",
                name="fk_grades_essay_versions",
            ),
            nullable=False,
            unique=True,
        ),
        sa.Column("total_score", sa.Numeric(6, 2), nullable=False),
        sa.Column("max_possible_score", sa.Numeric(6, 2), nullable=False),
        sa.Column("summary_feedback", sa.Text(), nullable=False),
        sa.Column("summary_feedback_edited", sa.Text(), nullable=True),
        sa.Column(
            "strictness",
            postgresql.ENUM(
                "lenient",
                "balanced",
                "strict",
                name="strictnesslevel",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("ai_model", sa.String(100), nullable=False),
        sa.Column("prompt_version", sa.String(100), nullable=False),
        sa.Column(
            "is_locked",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_grades_essay_version_id", "grades", ["essay_version_id"])

    # ------------------------------------------------------------------
    # 12. criterion_scores
    # ------------------------------------------------------------------
    op.create_table(
        "criterion_scores",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "grade_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("grades.id", ondelete="CASCADE", name="fk_criterion_scores_grades"),
            nullable=False,
        ),
        sa.Column(
            "rubric_criterion_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "rubric_criteria.id",
                ondelete="RESTRICT",
                name="fk_criterion_scores_rubric_criteria",
            ),
            nullable=False,
        ),
        sa.Column("ai_score", sa.Integer(), nullable=False),
        sa.Column("teacher_score", sa.Integer(), nullable=True),
        # COALESCE(teacher_score, ai_score) — application must keep in sync.
        sa.Column("final_score", sa.Integer(), nullable=False),
        sa.Column("ai_justification", sa.Text(), nullable=False),
        sa.Column("teacher_feedback", sa.Text(), nullable=True),
        sa.Column(
            "confidence",
            postgresql.ENUM(
                "high",
                "medium",
                "low",
                name="confidencelevel",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_criterion_scores_grade_id", "criterion_scores", ["grade_id"])
    op.create_index(
        "ix_criterion_scores_rubric_criterion_id",
        "criterion_scores",
        ["rubric_criterion_id"],
    )

    # ------------------------------------------------------------------
    # 13. Foreign key: audit_logs.teacher_id → users.id
    #     (deferred from 004_audit_logs to ensure the FK is added after
    #     the users table existed and this migration has run all tables)
    #
    #     Added as NOT VALID because audit_logs may already contain rows
    #     written before referential integrity was enforced. NOT VALID
    #     protects new writes immediately while allowing a separate
    #     VALIDATE CONSTRAINT step once stale rows are cleaned up,
    #     with no long scan / lock on the existing table.
    #
    #     ON DELETE RESTRICT prevents user deletion from silently
    #     NULLing audit log rows; combined with the INSERT-only trigger
    #     below, any SET NULL cascade would attempt an UPDATE and be
    #     rejected — so RESTRICT is the only safe option here.
    # ------------------------------------------------------------------
    op.execute(
        sa.text("""
        ALTER TABLE audit_logs
        ADD CONSTRAINT fk_audit_logs_users
        FOREIGN KEY (teacher_id)
        REFERENCES users (id)
        ON DELETE RESTRICT
        NOT VALID
    """)
    )

    # ------------------------------------------------------------------
    # 14. INSERT-only enforcement on audit_logs
    #     A trigger raises an error if any row is UPDATEd or DELETEd,
    #     providing a hard database-level guarantee that audit_logs is
    #     append-only (SOC 2 CC6 / FERPA data-integrity requirement).
    # ------------------------------------------------------------------
    op.execute(
        sa.text("""
        CREATE OR REPLACE FUNCTION audit_logs_no_update_delete()
        RETURNS trigger
        LANGUAGE plpgsql AS
        $$
        BEGIN
            RAISE EXCEPTION
                'audit_logs is INSERT-only: UPDATE and DELETE are not permitted '
                '(action: %, id: %)', TG_OP, COALESCE(OLD.id::text, 'unknown');
            RETURN OLD;
        END;
        $$;
    """)
    )

    op.execute(
        sa.text("""
        CREATE TRIGGER audit_logs_immutable
        BEFORE UPDATE OR DELETE ON audit_logs
        FOR EACH ROW EXECUTE FUNCTION audit_logs_no_update_delete();
    """)
    )


# ---------------------------------------------------------------------------
# downgrade
# ---------------------------------------------------------------------------


def downgrade() -> None:
    bind = op.get_bind()

    # Remove INSERT-only trigger and its backing function.
    op.execute(sa.text("DROP TRIGGER IF EXISTS audit_logs_immutable ON audit_logs"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS audit_logs_no_update_delete()"))

    # Remove FK added to audit_logs.
    op.drop_constraint("fk_audit_logs_users", "audit_logs", type_="foreignkey")

    # Drop tables in reverse dependency order.
    op.drop_index("ix_criterion_scores_rubric_criterion_id", table_name="criterion_scores")
    op.drop_index("ix_criterion_scores_grade_id", table_name="criterion_scores")
    op.drop_table("criterion_scores")

    op.drop_index("ix_grades_essay_version_id", table_name="grades")
    op.drop_table("grades")

    op.drop_index("ix_essay_versions_essay_id", table_name="essay_versions")
    op.drop_table("essay_versions")

    op.drop_index("ix_essays_assignment_id_student_id", table_name="essays")
    op.drop_index("ix_essays_student_id", table_name="essays")
    op.drop_index("ix_essays_assignment_id", table_name="essays")
    op.drop_table("essays")

    op.drop_index("ix_assignments_rubric_id", table_name="assignments")
    op.drop_index("ix_assignments_class_id", table_name="assignments")
    op.drop_table("assignments")

    op.drop_index("ix_rubric_criteria_rubric_id", table_name="rubric_criteria")
    op.drop_table("rubric_criteria")

    op.drop_index("ix_rubrics_teacher_id", table_name="rubrics")
    op.drop_table("rubrics")

    op.drop_index("ix_class_enrollments_active", table_name="class_enrollments")
    op.drop_index("ix_class_enrollments_student_id", table_name="class_enrollments")
    op.drop_index("ix_class_enrollments_class_id", table_name="class_enrollments")
    op.drop_table("class_enrollments")

    op.drop_index("ix_students_teacher_id", table_name="students")
    op.drop_table("students")

    op.drop_index("ix_classes_teacher_id_academic_year_is_archived", table_name="classes")
    op.drop_table("classes")

    # Drop ENUM types.
    _drop_enums(bind)

    # Intentionally leave the pgvector extension installed on downgrade.
    # Extensions are database-wide objects and may have existed before this
    # app was installed or still be required by other schemas.
