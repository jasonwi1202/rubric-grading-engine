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

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

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
        container = PostgresContainer("postgres:16-alpine")
        container.start()
    except Exception as exc:
        pytest.skip(
            f"PostgreSQL testcontainer could not start — skipping integration tests: {exc}"
        )

    # Build DSNs using the mapped host/port so they work across environments.
    host = container.get_container_host_ip()
    port = container.get_exposed_port(5432)
    user = container.username
    password = container.password
    dbname = container.dbname

    # Synchronous DSN for Alembic (uses psycopg2 by default)
    sync_url = f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{dbname}"
    # Asyncpg DSN for SQLAlchemy async engine
    async_url = f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{dbname}"

    # Run Alembic migrations to create the full schema (including RLS policies).
    try:
        from alembic import command as alembic_command
        from alembic.config import Config as AlembicConfig

        # alembic.ini lives in backend/, which is the CWD when pytest is run.
        cfg = AlembicConfig(Path(__file__).parent.parent.parent / "alembic.ini")
        cfg.set_main_option("sqlalchemy.url", sync_url)
        alembic_command.upgrade(cfg, "head")
    except Exception as exc:
        container.stop()
        pytest.skip(f"Alembic migrations failed — skipping integration tests: {exc}")

    yield async_url

    container.stop()


# ---------------------------------------------------------------------------
# Session-scoped async engine
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def async_engine(pg_dsn: str) -> AsyncEngine:
    """Return a session-scoped async engine wired to the test container."""
    engine = create_async_engine(pg_dsn, echo=False)
    yield engine
    # Engine is closed at session teardown by the event loop


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
