"""feedback_tone: add feedback_tone to assignments, ai_feedback to criterion_scores

Revision ID: 009_feedback_tone
Revises: 008_rubric_templates
Create Date: 2026-04-21 00:00:00.000000

Adds feedback-generation fields introduced by M3.18:

  - Creates ENUM type ``feedbacktonelevel`` with values
    ``encouraging``, ``direct``, ``academic``.
  - Adds ``feedback_tone`` column to ``assignments`` (NOT NULL, default
    ``'direct'``).  All existing rows receive the default value, so no
    back-fill step is required.
  - Adds ``ai_feedback`` column to ``criterion_scores`` (TEXT, nullable).
    Existing rows that pre-date M3.18 have no per-criterion feedback, so
    ``NULL`` is the correct default.

Downgrade reverses both column additions and drops the new ENUM type.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "009_feedback_tone"
down_revision: str | None = "008_rubric_templates"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_FEEDBACK_TONE_ENUM = postgresql.ENUM(
    "encouraging",
    "direct",
    "academic",
    name="feedbacktonelevel",
)


def upgrade() -> None:
    bind = op.get_bind()

    # 1. Create the new ENUM type.
    _FEEDBACK_TONE_ENUM.create(bind, checkfirst=True)

    # 2. Add feedback_tone to assignments (NOT NULL, default 'direct').
    #    server_default ensures existing rows receive the default without a
    #    separate UPDATE pass and avoids a long table-scan lock.
    op.add_column(
        "assignments",
        sa.Column(
            "feedback_tone",
            postgresql.ENUM(
                "encouraging",
                "direct",
                "academic",
                name="feedbacktonelevel",
                create_type=False,
            ),
            nullable=False,
            server_default="direct",
        ),
    )

    # 3. Add ai_feedback to criterion_scores (TEXT, nullable).
    #    NULL is correct for rows written before M3.18 (no feedback requested).
    op.add_column(
        "criterion_scores",
        sa.Column("ai_feedback", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    bind = op.get_bind()

    # Remove columns in reverse order.
    op.drop_column("criterion_scores", "ai_feedback")
    op.drop_column("assignments", "feedback_tone")

    # Drop the ENUM type last (after all columns that reference it are gone).
    _FEEDBACK_TONE_ENUM.drop(bind, checkfirst=True)
