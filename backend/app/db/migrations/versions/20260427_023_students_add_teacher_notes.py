"""students: add teacher_notes column

Revision ID: 023_students_teacher_notes
Revises: 022_student_skill_profiles
Create Date: 2026-04-27 00:00:00.000000

Adds a nullable ``teacher_notes`` TEXT column to ``students`` so teachers can
record private instructional notes per student.  Notes are visible only to the
owning teacher and are never shared with students.

Zero-downtime notes:
- Column is nullable with no default — no table rewrite required.
- Existing rows receive NULL, which is the correct initial state (no notes yet).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "023_students_teacher_notes"
down_revision: str | None = "022_student_skill_profiles"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "students",
        sa.Column(
            "teacher_notes",
            sa.Text(),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("students", "teacher_notes")
