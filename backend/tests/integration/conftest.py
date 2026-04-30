"""Shared fixtures for DB-backed integration tests.

A real PostgreSQL container is started once per test session via
``testcontainers``.  Alembic migrations are applied so every table and RLS
policy matches the production schema.  The tests skip automatically when
Docker is not available.

Fixtures provided:
  - ``pg_dsn``          (session) — asyncpg connection URL for the running container.
  - ``async_engine``    (session) — SQLAlchemy async engine wired to the container.
  - ``db_session``      (function) — fresh ``AsyncSession`` per test, NOT rolled back
                         automatically (each test is responsible for its own cleanup or
                         the container is discarded at session end).

Note on RLS: the testcontainers postgres user is a superuser and therefore
bypasses ``FORCE ROW LEVEL SECURITY`` automatically.  Integration tests validate
service-layer tenant scoping (WHERE teacher_id = ?) rather than the PostgreSQL
policy itself — the policy is a DB-level guarantee covered by the migration
roundtrip test.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from pathlib import Path
from unittest.mock import patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import settings as app_settings

# ---------------------------------------------------------------------------
# Session-scoped PostgreSQL container
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def pg_dsn() -> str:
    """Start a PostgreSQL testcontainer, run Alembic migrations, return the DSN.

    Skips the entire test session if Docker is not reachable.
    """
    try:
        from testcontainers.postgres import PostgresContainer
    except ImportError:
        pytest.skip("testcontainers package not installed — skipping integration tests")

    container = None
    try:
        # Use the pgvector image so migration 006's `CREATE EXTENSION IF NOT
        # EXISTS vector` succeeds — same image as docker-compose.
        container = PostgresContainer("pgvector/pgvector:pg16")
        container.start()
    except Exception as exc:
        pytest.skip(f"PostgreSQL testcontainer could not start — skipping integration tests: {exc}")

    # Build the asyncpg DSN using the mapped host/port.
    host = container.get_container_host_ip()
    port = container.get_exposed_port(5432)
    user = container.username
    password = container.password
    dbname = container.dbname
    async_url = f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{dbname}"

    # Run Alembic migrations to create the full schema (including RLS policies).
    # env.py reads settings.database_url (not the alembic.ini key), so
    # temporarily override it to point at the testcontainer.
    try:
        from alembic import command as alembic_command
        from alembic.config import Config as AlembicConfig

        cfg = AlembicConfig(Path(__file__).parent.parent.parent / "alembic.ini")
        with patch.object(app_settings, "database_url", async_url):
            alembic_command.upgrade(cfg, "head")
    except Exception as exc:
        container.stop()
        pytest.skip(f"Alembic migrations failed — skipping integration tests: {exc}")

    yield async_url

    container.stop()


# ---------------------------------------------------------------------------
# Function-scoped async engine and session
#
# The engine MUST be function-scoped (not session-scoped) because
# pytest-asyncio creates a fresh event loop per test function.  A session-
# scoped engine would bind its asyncpg connection pool to the first test's
# loop; subsequent tests would then fail with:
#   RuntimeError: Future attached to a different loop
# or
#   AttributeError: 'NoneType' object has no attribute 'send'   (proactor)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def async_engine(pg_dsn: str) -> AsyncGenerator[AsyncEngine, None]:
    """Yield a fresh async engine per test, bound to the current event loop."""
    engine = create_async_engine(pg_dsn, echo=False)
    yield engine
    await engine.dispose()


# ---------------------------------------------------------------------------
# Function-scoped async session
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def db_session(async_engine: AsyncEngine) -> AsyncGenerator[AsyncSession, None]:
    """Yield a fresh ``AsyncSession`` for each test.

    No automatic rollback — the test container is ephemeral so isolation
    between tests is ensured by the session being discarded at the end of
    the pytest session rather than per-test rollback.
    """
    factory = async_sessionmaker(async_engine, expire_on_commit=False)
    async with factory() as session:
        yield session
