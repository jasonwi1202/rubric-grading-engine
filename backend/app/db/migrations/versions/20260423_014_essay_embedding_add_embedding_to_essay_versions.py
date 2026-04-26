"""essay_embedding: add embedding column to essay_versions

Revision ID: 014_essay_embedding
Revises: 013_integrity_report
Create Date: 2026-04-23 01:00:00.000000

Adds a ``vector(1536)`` column to ``essay_versions`` for storing OpenAI
text-embedding-3-small embeddings (1 536 dimensions).  The column is
nullable so that existing essay version rows remain valid without a
back-fill pass; rows written after M4.4 always have a value once the
``compute_essay_embedding`` Celery task completes.

The ``vector`` extension was already enabled in migration 006_core_schema
via ``CREATE EXTENSION IF NOT EXISTS vector``, so no extension DDL is
needed here.

Downgrade removes the column.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

# revision identifiers, used by Alembic.
revision: str = "014_essay_embedding"
down_revision: str | None = "013_integrity_report"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_EMBEDDING_DIM = 1536


def upgrade() -> None:
    op.add_column(
        "essay_versions",
        sa.Column(
            "embedding",
            Vector(_EMBEDDING_DIM),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("essay_versions", "embedding")
