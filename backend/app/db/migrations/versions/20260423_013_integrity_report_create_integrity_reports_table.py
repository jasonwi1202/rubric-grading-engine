"""integrity_report: create integrity_reports table

Revision ID: 013_integrity_report
Revises: 012_confidence_scoring
Create Date: 2026-04-23 00:01:00.000000

Creates the ``integrity_reports`` table introduced by M4.3.

Each row records the result of an AI-integrity or plagiarism check run against
a specific essay version.  The table is scoped to a teacher via ``teacher_id``
and references the checked essay version via ``essay_version_id``.

New ENUM type ``integritystatus`` (values: pending, reviewed_clear, flagged) is
created in upgrade() and dropped in downgrade().
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "013_integrity_report"
down_revision: str | None = "012_confidence_scoring"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INTEGRITY_STATUS_ENUM = postgresql.ENUM(
    "pending",
    "reviewed_clear",
    "flagged",
    name="integritystatus",
)


def upgrade() -> None:
    bind = op.get_bind()
    _INTEGRITY_STATUS_ENUM.create(bind, checkfirst=True)

    op.create_table(
        "integrity_reports",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "essay_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "essay_versions.id",
                ondelete="CASCADE",
                name="fk_integrity_reports_essay_versions",
            ),
            nullable=False,
        ),
        sa.Column(
            "teacher_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "users.id",
                ondelete="CASCADE",
                name="fk_integrity_reports_users",
            ),
            nullable=False,
        ),
        sa.Column("provider", sa.String(100), nullable=False),
        sa.Column("ai_likelihood", sa.Float(), nullable=True),
        sa.Column("similarity_score", sa.Float(), nullable=True),
        sa.Column("flagged_passages", postgresql.JSONB(), nullable=True),
        sa.Column(
            "status",
            postgresql.ENUM(
                "pending",
                "reviewed_clear",
                "flagged",
                name="integritystatus",
                create_type=False,
            ),
            nullable=False,
            server_default=sa.text("'pending'::integritystatus"),
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

    op.create_index(
        "ix_integrity_reports_essay_version_id",
        "integrity_reports",
        ["essay_version_id"],
    )
    op.create_index(
        "ix_integrity_reports_teacher_id",
        "integrity_reports",
        ["teacher_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_integrity_reports_teacher_id", table_name="integrity_reports")
    op.drop_index("ix_integrity_reports_essay_version_id", table_name="integrity_reports")
    op.drop_table("integrity_reports")

    bind = op.get_bind()
    # NOTE: Dropping the ``integritystatus`` ENUM is safe here because this
    # type is exclusively used by the ``integrity_reports`` table, which is
    # dropped in the same downgrade step.  No other table or schema depends on
    # this type, so dropping it carries no cross-schema risk.
    _INTEGRITY_STATUS_ENUM.drop(bind, checkfirst=True)
