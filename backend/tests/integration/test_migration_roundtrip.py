"""Migration roundtrip integration test.

Validates that the full Alembic migration chain can:
  1. Upgrade from an empty database to ``head``.
  2. Downgrade all the way back to ``base`` (before the first migration).
  3. Upgrade to ``head`` again.

This catches:
  - Broken downgrade paths that crash or silently corrupt data.
  - Idempotency issues where re-applying a migration after a rollback fails.
  - Constraint or index conflicts that appear only on a second upgrade.

The test runs against a dedicated fresh PostgreSQL testcontainer so it does
not interfere with the shared container used by other integration tests.

Note: The test requires Docker to be available in the test environment.  It
is skipped automatically when Docker is not reachable.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import patch

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_alembic(command_name: str, async_url: str, revision: str) -> None:
    """Apply an Alembic command (upgrade/downgrade) against ``async_url``."""
    from alembic import command as alembic_command
    from alembic.config import Config as AlembicConfig

    from app.config import settings as app_settings

    cfg = AlembicConfig(Path(__file__).parent.parent.parent / "alembic.ini")
    with patch.object(app_settings, "database_url", async_url):
        getattr(alembic_command, command_name)(cfg, revision)


async def _get_current_revision_async(async_url: str) -> str | None:
    """Return the current Alembic revision from the database using asyncpg."""
    engine = create_async_engine(async_url)
    try:
        async with engine.connect() as conn:
            # Check whether alembic_version table exists first.
            exists_result = await conn.execute(
                sa.text(
                    "SELECT EXISTS ("
                    "  SELECT 1 FROM information_schema.tables"
                    "  WHERE table_name = 'alembic_version'"
                    ")"
                )
            )
            if not exists_result.scalar():
                return None
            result = await conn.execute(
                sa.text("SELECT version_num FROM alembic_version LIMIT 1")
            )
            row = result.fetchone()
            return row[0] if row else None
    finally:
        await engine.dispose()


def _current_revision(async_url: str) -> str | None:
    """Synchronous wrapper around the async revision query."""
    return asyncio.run(_get_current_revision_async(async_url))


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_migration_upgrade_downgrade_upgrade_roundtrip() -> None:
    """Full upgrade → downgrade base → upgrade roundtrip succeeds without errors.

    A fresh PostgreSQL container is started for this test alone so the
    shared session-scoped container used by other integration tests is not
    affected by the downgrade.
    """
    try:
        from testcontainers.postgres import PostgresContainer
    except ImportError:
        pytest.skip("testcontainers package not installed — skipping migration roundtrip test")

    container = None
    try:
        container = PostgresContainer("pgvector/pgvector:pg16")
        container.start()
    except Exception as exc:
        pytest.skip(
            f"PostgreSQL testcontainer could not start — skipping migration roundtrip test: {exc}"
        )

    host = container.get_container_host_ip()
    port = container.get_exposed_port(5432)
    user = container.username
    password = container.password
    dbname = container.dbname
    async_url = f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{dbname}"

    try:
        # ------------------------------------------------------------------
        # Step 1: Upgrade from empty DB to head.
        # ------------------------------------------------------------------
        _run_alembic("upgrade", async_url, "head")
        head_rev = _current_revision(async_url)
        assert head_rev is not None, "Expected a head revision after upgrade, got None"

        # ------------------------------------------------------------------
        # Step 2: Downgrade all the way back to base (before migration 001).
        # ------------------------------------------------------------------
        _run_alembic("downgrade", async_url, "base")
        base_rev = _current_revision(async_url)
        assert base_rev is None, (
            f"Expected no revision after downgrade to base, got '{base_rev}'"
        )

        # ------------------------------------------------------------------
        # Step 3: Re-upgrade to head.  Must succeed cleanly (no duplicate
        # tables/indexes/constraints from a prior incomplete run).
        # ------------------------------------------------------------------
        _run_alembic("upgrade", async_url, "head")
        head_rev_2 = _current_revision(async_url)
        assert head_rev_2 == head_rev, (
            f"Head revision after re-upgrade ({head_rev_2!r}) "
            f"differs from first upgrade ({head_rev!r})"
        )

    finally:
        container.stop()
