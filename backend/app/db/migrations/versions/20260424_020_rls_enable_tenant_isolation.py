"""rls: enable Row Level Security on all tenant-scoped tables

Revision ID: 020_rls_tenant_isolation
Revises: 019_media_comment
Create Date: 2026-04-24 00:00:00.000000

Enables PostgreSQL Row Level Security (RLS) on the six tenant-scoped
tables so that — even if the application layer has a bug — no row from
one teacher can be returned in a query scoped to another teacher.

Tables covered:
  - classes        (direct teacher_id column)
  - students       (direct teacher_id column)
  - rubrics        (direct teacher_id column)
  - assignments    (teacher_id via classes JOIN)
  - essays         (teacher_id via assignments → classes JOIN)
  - grades         (teacher_id via essay_versions → essays → assignments → classes JOIN)

Design:
  1. RLS is ENABLED but NOT FORCED for each table, meaning PostgreSQL
     superusers and the table owner can bypass the policy without setting
     the session variable.  This keeps migrations and manual admin queries
     working without extra ceremony.

  2. A single PERMISSIVE policy named "tenant_isolation" is created FOR ALL
     operations.  The USING clause checks:

         teacher_id::text = current_setting('app.current_teacher_id', true)

     The second argument `true` makes `current_setting` return NULL rather
     than raising an error when the variable is not set.  When NULL, the
     comparison evaluates to NULL (not TRUE), which PostgreSQL treats as
     FALSE — so all rows are filtered out.  This is safe: unauthenticated
     queries against these tables return zero rows.

  3. The application must call
         SET LOCAL app.current_teacher_id = '<uuid>';
     at the start of each authenticated database transaction to activate
     the policy.  See ``app.db.session.set_tenant_context``.

  4. For tables without a direct teacher_id (assignments, essays, grades)
     the policy uses an EXISTS sub-query.  These sub-queries are efficient
     because the existing foreign-key indexes (ix_assignments_class_id,
     ix_essays_assignment_id, ix_essay_versions_essay_id) cover the join
     path.

Downgrade:
  Drops all six policies and disables RLS on each table, restoring the
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
    op.execute(
        sa.text("""
        CREATE POLICY tenant_isolation ON classes
        FOR ALL
        USING (
            teacher_id::text = current_setting('app.current_teacher_id', true)
        )
    """)
    )

    # ------------------------------------------------------------------
    # 2. students — direct teacher_id column
    # ------------------------------------------------------------------
    op.execute(sa.text("ALTER TABLE students ENABLE ROW LEVEL SECURITY"))
    op.execute(
        sa.text("""
        CREATE POLICY tenant_isolation ON students
        FOR ALL
        USING (
            teacher_id::text = current_setting('app.current_teacher_id', true)
        )
    """)
    )

    # ------------------------------------------------------------------
    # 3. rubrics — direct teacher_id column
    # ------------------------------------------------------------------
    op.execute(sa.text("ALTER TABLE rubrics ENABLE ROW LEVEL SECURITY"))
    op.execute(
        sa.text("""
        CREATE POLICY tenant_isolation ON rubrics
        FOR ALL
        USING (
            teacher_id::text = current_setting('app.current_teacher_id', true)
        )
    """)
    )

    # ------------------------------------------------------------------
    # 4. assignments — teacher_id through classes
    # ------------------------------------------------------------------
    op.execute(sa.text("ALTER TABLE assignments ENABLE ROW LEVEL SECURITY"))
    op.execute(
        sa.text("""
        CREATE POLICY tenant_isolation ON assignments
        FOR ALL
        USING (
            EXISTS (
                SELECT 1
                FROM classes c
                WHERE c.id = assignments.class_id
                  AND c.teacher_id::text = current_setting('app.current_teacher_id', true)
            )
        )
    """)
    )

    # ------------------------------------------------------------------
    # 5. essays — teacher_id through assignments → classes
    # ------------------------------------------------------------------
    op.execute(sa.text("ALTER TABLE essays ENABLE ROW LEVEL SECURITY"))
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
                  AND c.teacher_id::text = current_setting('app.current_teacher_id', true)
            )
        )
    """)
    )

    # ------------------------------------------------------------------
    # 6. grades — teacher_id through essay_versions → essays → assignments → classes
    # ------------------------------------------------------------------
    op.execute(sa.text("ALTER TABLE grades ENABLE ROW LEVEL SECURITY"))
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
                  AND c.teacher_id::text = current_setting('app.current_teacher_id', true)
            )
        )
    """)
    )


def downgrade() -> None:
    # Drop policies and disable RLS in reverse order.

    op.execute(sa.text("DROP POLICY IF EXISTS tenant_isolation ON grades"))
    op.execute(sa.text("ALTER TABLE grades DISABLE ROW LEVEL SECURITY"))

    op.execute(sa.text("DROP POLICY IF EXISTS tenant_isolation ON essays"))
    op.execute(sa.text("ALTER TABLE essays DISABLE ROW LEVEL SECURITY"))

    op.execute(sa.text("DROP POLICY IF EXISTS tenant_isolation ON assignments"))
    op.execute(sa.text("ALTER TABLE assignments DISABLE ROW LEVEL SECURITY"))

    op.execute(sa.text("DROP POLICY IF EXISTS tenant_isolation ON rubrics"))
    op.execute(sa.text("ALTER TABLE rubrics DISABLE ROW LEVEL SECURITY"))

    op.execute(sa.text("DROP POLICY IF EXISTS tenant_isolation ON students"))
    op.execute(sa.text("ALTER TABLE students DISABLE ROW LEVEL SECURITY"))

    op.execute(sa.text("DROP POLICY IF EXISTS tenant_isolation ON classes"))
    op.execute(sa.text("ALTER TABLE classes DISABLE ROW LEVEL SECURITY"))
