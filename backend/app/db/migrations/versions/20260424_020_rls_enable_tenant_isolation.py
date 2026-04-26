"""rls: enable Row Level Security on all tenant-scoped tables

Revision ID: 020_rls_tenant_isolation
Revises: 019_media_comment_is_banked
Create Date: 2026-04-24 00:00:00.000000

Enables PostgreSQL Row Level Security (RLS) on all tenant-scoped tables so
that — even if the application layer has a bug — no row from one teacher can
be returned in a query scoped to another teacher.

Tables covered:
  Direct teacher_id column:
    - classes
    - students
    - rubrics  (see note on system templates below)
    - comment_bank_entries
    - integrity_reports
    - media_comments
    - regrade_requests

  teacher_id via FK chain:
    - assignments        (teacher_id via classes JOIN)
    - essays             (teacher_id via assignments → classes JOIN)
    - essay_versions     (teacher_id via essays → assignments → classes JOIN)
    - grades             (teacher_id via essay_versions → essays → assignments → classes JOIN)
    - rubric_criteria    (teacher_id via rubrics JOIN; split policy for system templates)
    - criterion_scores   (teacher_id via grades → essay_versions → essays → assignments → classes JOIN)
    - class_enrollments  (teacher_id via classes JOIN)

Design:
  1. RLS is ENABLED AND FORCED for each table.  FORCE ROW LEVEL SECURITY
     means the policy also applies to the table owner, so even if the
     application role is the schema owner (common in dev / single-role
     setups) it cannot bypass the policy.  Migrations and admin tooling
     that need to bypass should connect as a PostgreSQL superuser
     (superusers always bypass RLS regardless of FORCE).

  2. For most tables a single PERMISSIVE policy named "tenant_isolation"
     is created FOR ALL operations.  The USING clause checks:

         teacher_id = NULLIF(current_setting('app.current_teacher_id', true), '')::uuid

     ``NULLIF(current_setting(...), '')`` converts both an unset variable (NULL
     via missing_ok=true) and a reset-to-empty variable ('') to NULL, so the
     comparison always evaluates to NULL (false) when no teacher is in context.
     Using UUID-to-UUID comparison (instead of ``teacher_id::text``) lets
     PostgreSQL use the existing btree index on teacher_id columns.

  3. rubrics — SPLIT POLICIES to support system templates:
     System rubric templates use teacher_id IS NULL and is_template=TRUE.
     A single equality policy would hide them from all teachers.  Instead
     two PERMISSIVE policies are used:
       - "tenant_isolation": teacher-owned rows (non-NULL teacher_id)
       - "system_templates_readable": rows where is_template=TRUE and
         teacher_id IS NULL are visible for SELECT to any authenticated
         session (i.e. when app.current_teacher_id is non-empty).
         INSERT/UPDATE/DELETE still require a matching teacher_id.

  4. The application must call
         SET app.current_teacher_id = '<uuid>';
     at the start of each authenticated request (scoped to the session, not
     just the transaction) to activate the policy, and reset it to '' before
     the connection is returned to the pool.  See ``app.db.session``.

  5. For tables without a direct teacher_id (assignments, essays, grades)
     the policy uses an EXISTS sub-query.  These sub-queries are efficient
     because the existing foreign-key indexes cover the join path.

Downgrade:
  Drops all policies and disables RLS on each table, restoring the
  pre-migration state exactly.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "020_rls_tenant_isolation"
down_revision: str | None = "019_media_comment_is_banked"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. classes — direct teacher_id column
    # ------------------------------------------------------------------
    op.execute(sa.text("ALTER TABLE classes ENABLE ROW LEVEL SECURITY"))
    op.execute(sa.text("ALTER TABLE classes FORCE ROW LEVEL SECURITY"))
    op.execute(
        sa.text("""
        CREATE POLICY tenant_isolation ON classes
        FOR ALL
        USING (
            teacher_id = NULLIF(current_setting('app.current_teacher_id', true), '')::uuid
        )
    """)
    )

    # ------------------------------------------------------------------
    # 2. students — direct teacher_id column
    # ------------------------------------------------------------------
    op.execute(sa.text("ALTER TABLE students ENABLE ROW LEVEL SECURITY"))
    op.execute(sa.text("ALTER TABLE students FORCE ROW LEVEL SECURITY"))
    op.execute(
        sa.text("""
        CREATE POLICY tenant_isolation ON students
        FOR ALL
        USING (
            teacher_id = NULLIF(current_setting('app.current_teacher_id', true), '')::uuid
        )
    """)
    )

    # ------------------------------------------------------------------
    # 3. rubrics — split policies for system templates + tenant rows
    #
    # System templates have teacher_id IS NULL and is_template=TRUE.  A
    # single equality policy would make them invisible to all teachers.
    # Two PERMISSIVE policies allow:
    #   - Any authenticated session to SELECT system templates.
    #   - Tenant-owned rows to be accessed only by their owner.
    # INSERT/UPDATE/DELETE on system templates is never permitted via the
    # app (teacher_id IS NULL fails the tenant_isolation WITH CHECK).
    # ------------------------------------------------------------------
    op.execute(sa.text("ALTER TABLE rubrics ENABLE ROW LEVEL SECURITY"))
    op.execute(sa.text("ALTER TABLE rubrics FORCE ROW LEVEL SECURITY"))
    op.execute(
        sa.text("""
        CREATE POLICY tenant_isolation ON rubrics
        FOR ALL
        USING (
            teacher_id = NULLIF(current_setting('app.current_teacher_id', true), '')::uuid
        )
    """)
    )
    op.execute(
        sa.text("""
        CREATE POLICY system_templates_readable ON rubrics
        FOR SELECT
        USING (
            teacher_id IS NULL
            AND is_template = true
            AND NULLIF(current_setting('app.current_teacher_id', true), '') IS NOT NULL
        )
    """)
    )

    # ------------------------------------------------------------------
    # 4. assignments — teacher_id through classes
    # ------------------------------------------------------------------
    op.execute(sa.text("ALTER TABLE assignments ENABLE ROW LEVEL SECURITY"))
    op.execute(sa.text("ALTER TABLE assignments FORCE ROW LEVEL SECURITY"))
    op.execute(
        sa.text("""
        CREATE POLICY tenant_isolation ON assignments
        FOR ALL
        USING (
            EXISTS (
                SELECT 1
                FROM classes c
                WHERE c.id = assignments.class_id
                  AND c.teacher_id = NULLIF(current_setting('app.current_teacher_id', true), '')::uuid
            )
        )
    """)
    )

    # ------------------------------------------------------------------
    # 5. essays — teacher_id through assignments → classes
    # ------------------------------------------------------------------
    op.execute(sa.text("ALTER TABLE essays ENABLE ROW LEVEL SECURITY"))
    op.execute(sa.text("ALTER TABLE essays FORCE ROW LEVEL SECURITY"))
    op.execute(
        sa.text("""
        CREATE POLICY tenant_isolation ON essays
        FOR ALL
        USING (
            EXISTS (
                SELECT 1
                FROM assignments a
                JOIN classes c ON c.id = a.class_id
                WHERE a.id = essays.assignment_id
                  AND c.teacher_id = NULLIF(current_setting('app.current_teacher_id', true), '')::uuid
            )
        )
    """)
    )

    # ------------------------------------------------------------------
    # 6. grades — teacher_id through essay_versions → essays → assignments → classes
    # ------------------------------------------------------------------
    op.execute(sa.text("ALTER TABLE grades ENABLE ROW LEVEL SECURITY"))
    op.execute(sa.text("ALTER TABLE grades FORCE ROW LEVEL SECURITY"))
    op.execute(
        sa.text("""
        CREATE POLICY tenant_isolation ON grades
        FOR ALL
        USING (
            EXISTS (
                SELECT 1
                FROM essay_versions ev
                JOIN essays e  ON e.id  = ev.essay_id
                JOIN assignments a ON a.id = e.assignment_id
                JOIN classes c ON c.id = a.class_id
                WHERE ev.id = grades.essay_version_id
                  AND c.teacher_id = NULLIF(current_setting('app.current_teacher_id', true), '')::uuid
            )
        )
    """)
    )

    # ------------------------------------------------------------------
    # 7. comment_bank_entries — direct teacher_id column
    # ------------------------------------------------------------------
    op.execute(sa.text("ALTER TABLE comment_bank_entries ENABLE ROW LEVEL SECURITY"))
    op.execute(sa.text("ALTER TABLE comment_bank_entries FORCE ROW LEVEL SECURITY"))
    op.execute(
        sa.text("""
        CREATE POLICY tenant_isolation ON comment_bank_entries
        FOR ALL
        USING (
            teacher_id = NULLIF(current_setting('app.current_teacher_id', true), '')::uuid
        )
    """)
    )

    # ------------------------------------------------------------------
    # 8. integrity_reports — direct teacher_id column
    # ------------------------------------------------------------------
    op.execute(sa.text("ALTER TABLE integrity_reports ENABLE ROW LEVEL SECURITY"))
    op.execute(sa.text("ALTER TABLE integrity_reports FORCE ROW LEVEL SECURITY"))
    op.execute(
        sa.text("""
        CREATE POLICY tenant_isolation ON integrity_reports
        FOR ALL
        USING (
            teacher_id = NULLIF(current_setting('app.current_teacher_id', true), '')::uuid
        )
    """)
    )

    # ------------------------------------------------------------------
    # 9. media_comments — direct teacher_id column
    # ------------------------------------------------------------------
    op.execute(sa.text("ALTER TABLE media_comments ENABLE ROW LEVEL SECURITY"))
    op.execute(sa.text("ALTER TABLE media_comments FORCE ROW LEVEL SECURITY"))
    op.execute(
        sa.text("""
        CREATE POLICY tenant_isolation ON media_comments
        FOR ALL
        USING (
            teacher_id = NULLIF(current_setting('app.current_teacher_id', true), '')::uuid
        )
    """)
    )

    # ------------------------------------------------------------------
    # 10. regrade_requests — direct teacher_id column
    # ------------------------------------------------------------------
    op.execute(sa.text("ALTER TABLE regrade_requests ENABLE ROW LEVEL SECURITY"))
    op.execute(sa.text("ALTER TABLE regrade_requests FORCE ROW LEVEL SECURITY"))
    op.execute(
        sa.text("""
        CREATE POLICY tenant_isolation ON regrade_requests
        FOR ALL
        USING (
            teacher_id = NULLIF(current_setting('app.current_teacher_id', true), '')::uuid
        )
    """)
    )

    # ------------------------------------------------------------------
    # 11. class_enrollments — teacher_id via classes
    # ------------------------------------------------------------------
    op.execute(sa.text("ALTER TABLE class_enrollments ENABLE ROW LEVEL SECURITY"))
    op.execute(sa.text("ALTER TABLE class_enrollments FORCE ROW LEVEL SECURITY"))
    op.execute(
        sa.text("""
        CREATE POLICY tenant_isolation ON class_enrollments
        FOR ALL
        USING (
            EXISTS (
                SELECT 1
                FROM classes c
                WHERE c.id = class_enrollments.class_id
                  AND c.teacher_id = NULLIF(current_setting('app.current_teacher_id', true), '')::uuid
            )
        )
    """)
    )

    # ------------------------------------------------------------------
    # 12. essay_versions — teacher_id via essays → assignments → classes
    # ------------------------------------------------------------------
    op.execute(sa.text("ALTER TABLE essay_versions ENABLE ROW LEVEL SECURITY"))
    op.execute(sa.text("ALTER TABLE essay_versions FORCE ROW LEVEL SECURITY"))
    op.execute(
        sa.text("""
        CREATE POLICY tenant_isolation ON essay_versions
        FOR ALL
        USING (
            EXISTS (
                SELECT 1
                FROM essays e
                JOIN assignments a ON a.id = e.assignment_id
                JOIN classes c ON c.id = a.class_id
                WHERE e.id = essay_versions.essay_id
                  AND c.teacher_id = NULLIF(current_setting('app.current_teacher_id', true), '')::uuid
            )
        )
    """)
    )

    # ------------------------------------------------------------------
    # 13. rubric_criteria — split policies mirroring rubrics
    #
    # Criteria belonging to teacher-owned rubrics are readable only by
    # their owner.  Criteria belonging to system template rubrics
    # (teacher_id IS NULL, is_template=TRUE) are readable by any
    # authenticated session, mirroring the system_templates_readable
    # policy on the parent rubrics table.
    # ------------------------------------------------------------------
    op.execute(sa.text("ALTER TABLE rubric_criteria ENABLE ROW LEVEL SECURITY"))
    op.execute(sa.text("ALTER TABLE rubric_criteria FORCE ROW LEVEL SECURITY"))
    op.execute(
        sa.text("""
        CREATE POLICY tenant_isolation ON rubric_criteria
        FOR ALL
        USING (
            EXISTS (
                SELECT 1
                FROM rubrics r
                WHERE r.id = rubric_criteria.rubric_id
                  AND r.teacher_id = NULLIF(current_setting('app.current_teacher_id', true), '')::uuid
            )
        )
    """)
    )
    op.execute(
        sa.text("""
        CREATE POLICY system_template_criteria_readable ON rubric_criteria
        FOR SELECT
        USING (
            EXISTS (
                SELECT 1
                FROM rubrics r
                WHERE r.id = rubric_criteria.rubric_id
                  AND r.teacher_id IS NULL
                  AND r.is_template = true
                  AND NULLIF(current_setting('app.current_teacher_id', true), '') IS NOT NULL
            )
        )
    """)
    )

    # ------------------------------------------------------------------
    # 14. criterion_scores — teacher_id via grades → essay_versions → essays
    #                        → assignments → classes
    # ------------------------------------------------------------------
    op.execute(sa.text("ALTER TABLE criterion_scores ENABLE ROW LEVEL SECURITY"))
    op.execute(sa.text("ALTER TABLE criterion_scores FORCE ROW LEVEL SECURITY"))
    op.execute(
        sa.text("""
        CREATE POLICY tenant_isolation ON criterion_scores
        FOR ALL
        USING (
            EXISTS (
                SELECT 1
                FROM grades g
                JOIN essay_versions ev ON ev.id = g.essay_version_id
                JOIN essays e ON e.id = ev.essay_id
                JOIN assignments a ON a.id = e.assignment_id
                JOIN classes c ON c.id = a.class_id
                WHERE g.id = criterion_scores.grade_id
                  AND c.teacher_id = NULLIF(current_setting('app.current_teacher_id', true), '')::uuid
            )
        )
    """)
    )


def downgrade() -> None:
    # Drop policies and disable/unforce RLS in reverse order.

    op.execute(sa.text("DROP POLICY IF EXISTS tenant_isolation ON criterion_scores"))
    op.execute(sa.text("ALTER TABLE criterion_scores NO FORCE ROW LEVEL SECURITY"))
    op.execute(sa.text("ALTER TABLE criterion_scores DISABLE ROW LEVEL SECURITY"))

    op.execute(
        sa.text("DROP POLICY IF EXISTS system_template_criteria_readable ON rubric_criteria")
    )
    op.execute(sa.text("DROP POLICY IF EXISTS tenant_isolation ON rubric_criteria"))
    op.execute(sa.text("ALTER TABLE rubric_criteria NO FORCE ROW LEVEL SECURITY"))
    op.execute(sa.text("ALTER TABLE rubric_criteria DISABLE ROW LEVEL SECURITY"))

    op.execute(sa.text("DROP POLICY IF EXISTS tenant_isolation ON essay_versions"))
    op.execute(sa.text("ALTER TABLE essay_versions NO FORCE ROW LEVEL SECURITY"))
    op.execute(sa.text("ALTER TABLE essay_versions DISABLE ROW LEVEL SECURITY"))

    op.execute(sa.text("DROP POLICY IF EXISTS tenant_isolation ON class_enrollments"))
    op.execute(sa.text("ALTER TABLE class_enrollments NO FORCE ROW LEVEL SECURITY"))
    op.execute(sa.text("ALTER TABLE class_enrollments DISABLE ROW LEVEL SECURITY"))

    op.execute(sa.text("DROP POLICY IF EXISTS tenant_isolation ON regrade_requests"))
    op.execute(sa.text("ALTER TABLE regrade_requests NO FORCE ROW LEVEL SECURITY"))
    op.execute(sa.text("ALTER TABLE regrade_requests DISABLE ROW LEVEL SECURITY"))

    op.execute(sa.text("DROP POLICY IF EXISTS tenant_isolation ON media_comments"))
    op.execute(sa.text("ALTER TABLE media_comments NO FORCE ROW LEVEL SECURITY"))
    op.execute(sa.text("ALTER TABLE media_comments DISABLE ROW LEVEL SECURITY"))

    op.execute(sa.text("DROP POLICY IF EXISTS tenant_isolation ON integrity_reports"))
    op.execute(sa.text("ALTER TABLE integrity_reports NO FORCE ROW LEVEL SECURITY"))
    op.execute(sa.text("ALTER TABLE integrity_reports DISABLE ROW LEVEL SECURITY"))

    op.execute(sa.text("DROP POLICY IF EXISTS tenant_isolation ON comment_bank_entries"))
    op.execute(sa.text("ALTER TABLE comment_bank_entries NO FORCE ROW LEVEL SECURITY"))
    op.execute(sa.text("ALTER TABLE comment_bank_entries DISABLE ROW LEVEL SECURITY"))

    op.execute(sa.text("DROP POLICY IF EXISTS tenant_isolation ON grades"))
    op.execute(sa.text("ALTER TABLE grades NO FORCE ROW LEVEL SECURITY"))
    op.execute(sa.text("ALTER TABLE grades DISABLE ROW LEVEL SECURITY"))

    op.execute(sa.text("DROP POLICY IF EXISTS tenant_isolation ON essays"))
    op.execute(sa.text("ALTER TABLE essays NO FORCE ROW LEVEL SECURITY"))
    op.execute(sa.text("ALTER TABLE essays DISABLE ROW LEVEL SECURITY"))

    op.execute(sa.text("DROP POLICY IF EXISTS tenant_isolation ON assignments"))
    op.execute(sa.text("ALTER TABLE assignments NO FORCE ROW LEVEL SECURITY"))
    op.execute(sa.text("ALTER TABLE assignments DISABLE ROW LEVEL SECURITY"))

    op.execute(sa.text("DROP POLICY IF EXISTS system_templates_readable ON rubrics"))
    op.execute(sa.text("DROP POLICY IF EXISTS tenant_isolation ON rubrics"))
    op.execute(sa.text("ALTER TABLE rubrics NO FORCE ROW LEVEL SECURITY"))
    op.execute(sa.text("ALTER TABLE rubrics DISABLE ROW LEVEL SECURITY"))

    op.execute(sa.text("DROP POLICY IF EXISTS tenant_isolation ON students"))
    op.execute(sa.text("ALTER TABLE students NO FORCE ROW LEVEL SECURITY"))
    op.execute(sa.text("ALTER TABLE students DISABLE ROW LEVEL SECURITY"))

    op.execute(sa.text("DROP POLICY IF EXISTS tenant_isolation ON classes"))
    op.execute(sa.text("ALTER TABLE classes NO FORCE ROW LEVEL SECURITY"))
    op.execute(sa.text("ALTER TABLE classes DISABLE ROW LEVEL SECURITY"))
