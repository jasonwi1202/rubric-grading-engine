"""rubric_templates: make teacher_id nullable and seed system templates

Revision ID: 008_rubric_templates
Revises: 007_rubrics_deleted_at
Create Date: 2026-04-20 00:00:00.000000

Changes:
  - Makes ``rubrics.teacher_id`` nullable so that system-owned templates
    can be stored without a teacher owner (``teacher_id IS NULL``).
  - Seeds three system rubric templates (``is_template=True``,
    ``teacher_id=NULL``) from which teachers can start their rubrics:
      1. 5-Paragraph Essay
      2. Argumentative Essay
      3. Research Paper

Downgrade removes the seeded rows and re-adds the NOT NULL constraint.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import insert as pg_insert

# revision identifiers, used by Alembic.
revision: str = "008_rubric_templates"
down_revision: str | None = "007_rubrics_deleted_at"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# ---------------------------------------------------------------------------
# System template seed data
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 4, 20, 0, 0, 0, tzinfo=UTC)

# Pre-generated stable UUIDs for the system templates and their criteria so
# that the inserts use ON CONFLICT DO NOTHING and can be safely re-applied
# after a partial/interrupted upgrade.

_FIVE_PARA_ID = uuid.UUID("00000000-0000-0000-0001-000000000001")
_ARGUMENTATIVE_ID = uuid.UUID("00000000-0000-0000-0001-000000000002")
_RESEARCH_PAPER_ID = uuid.UUID("00000000-0000-0000-0001-000000000003")

_SYSTEM_TEMPLATE_IDS = [_FIVE_PARA_ID, _ARGUMENTATIVE_ID, _RESEARCH_PAPER_ID]

_RUBRICS = [
    {
        "id": _FIVE_PARA_ID,
        "teacher_id": None,
        "name": "5-Paragraph Essay",
        "description": (
            "A standard rubric for evaluating five-paragraph essays covering "
            "thesis, evidence, organisation, and mechanics."
        ),
        "is_template": True,
        "created_at": _NOW,
        "updated_at": _NOW,
        "deleted_at": None,
    },
    {
        "id": _ARGUMENTATIVE_ID,
        "teacher_id": None,
        "name": "Argumentative Essay",
        "description": (
            "Evaluates the strength of a claim, quality of evidence and "
            "reasoning, handling of counterarguments, and writing style."
        ),
        "is_template": True,
        "created_at": _NOW,
        "updated_at": _NOW,
        "deleted_at": None,
    },
    {
        "id": _RESEARCH_PAPER_ID,
        "teacher_id": None,
        "name": "Research Paper",
        "description": (
            "Assesses thesis focus, depth of research, analysis and synthesis "
            "of sources, organisation, and citation accuracy."
        ),
        "is_template": True,
        "created_at": _NOW,
        "updated_at": _NOW,
        "deleted_at": None,
    },
]

_CRITERIA = [
    # --- 5-Paragraph Essay ---
    {
        "id": uuid.UUID("00000000-0000-0000-0002-000000000001"),
        "rubric_id": _FIVE_PARA_ID,
        "name": "Thesis Statement",
        "description": (
            "Does the essay present a clear, arguable thesis that previews the "
            "three body paragraphs?"
        ),
        "weight": "25.00",
        "min_score": 1,
        "max_score": 5,
        "display_order": 0,
        "anchor_descriptions": None,
    },
    {
        "id": uuid.UUID("00000000-0000-0000-0002-000000000002"),
        "rubric_id": _FIVE_PARA_ID,
        "name": "Supporting Evidence",
        "description": (
            "Are the three body paragraphs supported with relevant, specific "
            "evidence and explanation?"
        ),
        "weight": "25.00",
        "min_score": 1,
        "max_score": 5,
        "display_order": 1,
        "anchor_descriptions": None,
    },
    {
        "id": uuid.UUID("00000000-0000-0000-0002-000000000003"),
        "rubric_id": _FIVE_PARA_ID,
        "name": "Organization",
        "description": (
            "Does the essay follow a logical five-paragraph structure with "
            "clear transitions between paragraphs?"
        ),
        "weight": "25.00",
        "min_score": 1,
        "max_score": 5,
        "display_order": 2,
        "anchor_descriptions": None,
    },
    {
        "id": uuid.UUID("00000000-0000-0000-0002-000000000004"),
        "rubric_id": _FIVE_PARA_ID,
        "name": "Grammar & Mechanics",
        "description": (
            "Is the writing free of major grammatical, spelling, and punctuation errors?"
        ),
        "weight": "25.00",
        "min_score": 1,
        "max_score": 5,
        "display_order": 3,
        "anchor_descriptions": None,
    },
    # --- Argumentative Essay ---
    {
        "id": uuid.UUID("00000000-0000-0000-0002-000000000005"),
        "rubric_id": _ARGUMENTATIVE_ID,
        "name": "Claim",
        "description": (
            "Does the essay state a clear, specific, and debatable claim "
            "that is maintained throughout?"
        ),
        "weight": "30.00",
        "min_score": 1,
        "max_score": 5,
        "display_order": 0,
        "anchor_descriptions": None,
    },
    {
        "id": uuid.UUID("00000000-0000-0000-0002-000000000006"),
        "rubric_id": _ARGUMENTATIVE_ID,
        "name": "Evidence & Reasoning",
        "description": (
            "Does the writer support the claim with credible evidence and "
            "clearly explain how it supports the argument?"
        ),
        "weight": "30.00",
        "min_score": 1,
        "max_score": 5,
        "display_order": 1,
        "anchor_descriptions": None,
    },
    {
        "id": uuid.UUID("00000000-0000-0000-0002-000000000007"),
        "rubric_id": _ARGUMENTATIVE_ID,
        "name": "Counterargument",
        "description": (
            "Does the essay acknowledge and effectively refute at least one opposing viewpoint?"
        ),
        "weight": "20.00",
        "min_score": 1,
        "max_score": 5,
        "display_order": 2,
        "anchor_descriptions": None,
    },
    {
        "id": uuid.UUID("00000000-0000-0000-0002-000000000008"),
        "rubric_id": _ARGUMENTATIVE_ID,
        "name": "Style & Voice",
        "description": (
            "Does the writing demonstrate a confident, formal voice appropriate "
            "for persuasive writing, with varied sentence structure?"
        ),
        "weight": "20.00",
        "min_score": 1,
        "max_score": 5,
        "display_order": 3,
        "anchor_descriptions": None,
    },
    # --- Research Paper ---
    {
        "id": uuid.UUID("00000000-0000-0000-0002-000000000009"),
        "rubric_id": _RESEARCH_PAPER_ID,
        "name": "Thesis & Focus",
        "description": (
            "Is there a clear, focused thesis that guides the research and "
            "is sustained throughout the paper?"
        ),
        "weight": "20.00",
        "min_score": 1,
        "max_score": 5,
        "display_order": 0,
        "anchor_descriptions": None,
    },
    {
        "id": uuid.UUID("00000000-0000-0000-0002-000000000010"),
        "rubric_id": _RESEARCH_PAPER_ID,
        "name": "Research & Evidence",
        "description": (
            "Does the paper incorporate credible, relevant, and sufficient "
            "sources to support its argument?"
        ),
        "weight": "25.00",
        "min_score": 1,
        "max_score": 5,
        "display_order": 1,
        "anchor_descriptions": None,
    },
    {
        "id": uuid.UUID("00000000-0000-0000-0002-000000000011"),
        "rubric_id": _RESEARCH_PAPER_ID,
        "name": "Analysis & Synthesis",
        "description": (
            "Does the writer analyse, interpret, and synthesise sources rather "
            "than merely summarising them?"
        ),
        "weight": "25.00",
        "min_score": 1,
        "max_score": 5,
        "display_order": 2,
        "anchor_descriptions": None,
    },
    {
        "id": uuid.UUID("00000000-0000-0000-0002-000000000012"),
        "rubric_id": _RESEARCH_PAPER_ID,
        "name": "Organization",
        "description": (
            "Is the paper logically structured with a clear introduction, "
            "body sections, and conclusion?"
        ),
        "weight": "20.00",
        "min_score": 1,
        "max_score": 5,
        "display_order": 3,
        "anchor_descriptions": None,
    },
    {
        "id": uuid.UUID("00000000-0000-0000-0002-000000000013"),
        "rubric_id": _RESEARCH_PAPER_ID,
        "name": "Citations & Mechanics",
        "description": (
            "Are sources cited correctly using the required format, and is the "
            "writing free of major mechanical errors?"
        ),
        "weight": "10.00",
        "min_score": 1,
        "max_score": 5,
        "display_order": 4,
        "anchor_descriptions": None,
    },
]


def upgrade() -> None:
    # 1. Make teacher_id nullable (safe — only relaxes an existing constraint).
    op.alter_column("rubrics", "teacher_id", nullable=True)

    # 2. Seed system rubric templates.
    rubrics_table = sa.table(
        "rubrics",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("teacher_id", postgresql.UUID(as_uuid=True)),
        sa.column("name", sa.Text),
        sa.column("description", sa.Text),
        sa.column("is_template", sa.Boolean),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
        sa.column("deleted_at", sa.DateTime(timezone=True)),
    )
    # Use ON CONFLICT DO NOTHING so the migration is safe to re-run after a
    # partial/failed upgrade (duplicate IDs silently skip instead of failing).
    op.execute(
        pg_insert(rubrics_table).values(_RUBRICS).on_conflict_do_nothing(index_elements=["id"])
    )

    criteria_table = sa.table(
        "rubric_criteria",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("rubric_id", postgresql.UUID(as_uuid=True)),
        sa.column("name", sa.Text),
        sa.column("description", sa.Text),
        sa.column("weight", sa.Numeric(5, 2)),
        sa.column("min_score", sa.Integer),
        sa.column("max_score", sa.Integer),
        sa.column("display_order", sa.Integer),
        sa.column("anchor_descriptions", postgresql.JSONB()),
    )
    op.execute(
        pg_insert(criteria_table).values(_CRITERIA).on_conflict_do_nothing(index_elements=["id"])
    )


def downgrade() -> None:
    # 1. Remove seeded system template criteria.
    rubric_criteria_t = sa.table(
        "rubric_criteria",
        sa.column("rubric_id", postgresql.UUID(as_uuid=True)),
    )
    op.execute(
        rubric_criteria_t.delete().where(rubric_criteria_t.c.rubric_id.in_(_SYSTEM_TEMPLATE_IDS))
    )

    # 2. Remove seeded system template rubrics.
    rubrics_t = sa.table(
        "rubrics",
        sa.column("id", postgresql.UUID(as_uuid=True)),
    )
    op.execute(rubrics_t.delete().where(rubrics_t.c.id.in_(_SYSTEM_TEMPLATE_IDS)))

    # 3. Guard: verify no remaining NULL teacher_id rows exist before
    #    restoring the NOT NULL constraint.  Any such rows would be
    #    application-layer bugs (teacher_id may only be NULL for the seeded
    #    system templates removed above).  Failing loudly here prevents a
    #    silent data-integrity hole; recovery requires removing the rogue
    #    rows manually and re-running the downgrade.
    result = op.get_bind().execute(sa.text("SELECT COUNT(*) FROM rubrics WHERE teacher_id IS NULL"))
    null_count = result.scalar()
    if null_count is not None and null_count > 0:
        raise RuntimeError(
            f"Cannot downgrade migration 008: {null_count} rubric row(s) still have "
            "teacher_id IS NULL after removing the seeded system templates. "
            "Remove or reassign these rows manually before re-running the downgrade."
        )

    # 4. Re-add NOT NULL constraint (safe because the guard above confirmed
    #    no NULL rows remain).
    op.alter_column("rubrics", "teacher_id", nullable=False)
