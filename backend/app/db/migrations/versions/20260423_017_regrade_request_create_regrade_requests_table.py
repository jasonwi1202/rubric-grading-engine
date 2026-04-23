"""regrade_request: create regrade_requests table

Revision ID: 017_regrade_request
Revises: 016_integrity_report_reviewed_at
Create Date: 2026-04-23 04:00:00.000000

Creates the ``regrade_requests`` table introduced by M4.7.

Each row records a teacher's request to reconsider an AI-generated grade or a
specific criterion score within that grade.  The teacher supplies a
``dispute_text``, and the reviewer records the outcome via ``status``,
``resolution_note``, and ``resolved_at``.

A new ENUM type ``regraderequeststatus`` (values: open, approved, denied) is
created in upgrade() and dropped in downgrade().

Zero-downtime notes:
- Creating a new table and a new ENUM type does not lock any existing table.
- The FK ``criterion_score_id`` uses ``ON DELETE SET NULL`` so that deleting a
  criterion score does not cascade-delete the regrade request, preserving the
  audit trail.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "017_regrade_request"
down_revision: str | None = "016_integrity_report_reviewed_at"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_REGRADE_STATUS_ENUM = postgresql.ENUM(
    "open",
    "approved",
    "denied",
    name="regraderequeststatus",
)


def upgrade() -> None:
    bind = op.get_bind()
    _REGRADE_STATUS_ENUM.create(bind, checkfirst=True)

    op.create_table(
        "regrade_requests",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "grade_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "grades.id",
                ondelete="CASCADE",
                name="fk_regrade_requests_grades",
            ),
            nullable=False,
        ),
        sa.Column(
            "criterion_score_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "criterion_scores.id",
                ondelete="SET NULL",
                name="fk_regrade_requests_criterion_scores",
            ),
            nullable=True,
        ),
        sa.Column(
            "teacher_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "users.id",
                ondelete="CASCADE",
                name="fk_regrade_requests_users",
            ),
            nullable=False,
        ),
        sa.Column("dispute_text", sa.Text(), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(
                "open",
                "approved",
                "denied",
                name="regraderequeststatus",
                create_type=False,
            ),
            nullable=False,
            server_default=sa.text("'open'::regraderequeststatus"),
        ),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )

    op.create_index(
        "ix_regrade_requests_grade_id",
        "regrade_requests",
        ["grade_id"],
    )
    op.create_index(
        "ix_regrade_requests_criterion_score_id",
        "regrade_requests",
        ["criterion_score_id"],
    )
    op.create_index(
        "ix_regrade_requests_teacher_id",
        "regrade_requests",
        ["teacher_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_regrade_requests_teacher_id", table_name="regrade_requests")
    op.drop_index("ix_regrade_requests_criterion_score_id", table_name="regrade_requests")
    op.drop_index("ix_regrade_requests_grade_id", table_name="regrade_requests")
    op.drop_table("regrade_requests")

    bind = op.get_bind()
    # NOTE: Dropping the ``regraderequeststatus`` ENUM is safe here because this
    # type is exclusively used by the ``regrade_requests`` table, which is
    # dropped in the same downgrade step.
    _REGRADE_STATUS_ENUM.drop(bind, checkfirst=True)
