"""media_comment: create media_comments table

Revision ID: 018_media_comment
Revises: 017_regrade_request
Create Date: 2026-04-24 00:00:00.000000

Creates the ``media_comments`` table introduced by M4.10.

Each row stores the metadata for an audio comment attached to a grade:
the S3 object key, recording duration in seconds, and MIME type.  The
audio blob itself is stored in S3 only; the key follows the format
``media/{teacher_id}/{grade_id}/{uuid}.webm`` so no student PII ever
appears in the key.

Zero-downtime notes:
- Creating a brand-new table acquires no locks on existing rows.
- Indexes on the new table are created inside the same transaction
  (table is empty, so CONCURRENTLY is not needed).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "018_media_comment"
down_revision: str | None = "017_regrade_request"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "media_comments",
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
                name="fk_media_comments_grades",
            ),
            nullable=False,
        ),
        sa.Column(
            "teacher_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "users.id",
                ondelete="CASCADE",
                name="fk_media_comments_users",
            ),
            nullable=False,
        ),
        # S3 object key — no student PII; format: media/{teacher_id}/{grade_id}/{uuid}.webm
        sa.Column("s3_key", sa.String(500), nullable=False),
        # Recording length in seconds (integer — MediaRecorder API duration).
        sa.Column("duration_seconds", sa.Integer(), nullable=False),
        # MIME type of the recorded blob, e.g. "audio/webm".
        sa.Column("mime_type", sa.String(100), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )

    op.create_index(
        "ix_media_comments_grade_id",
        "media_comments",
        ["grade_id"],
    )
    op.create_index(
        "ix_media_comments_teacher_id",
        "media_comments",
        ["teacher_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_media_comments_teacher_id", table_name="media_comments")
    op.drop_index("ix_media_comments_grade_id", table_name="media_comments")
    op.drop_table("media_comments")
