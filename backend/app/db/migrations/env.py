"""Alembic migration environment — async SQLAlchemy support.

This file is executed by the Alembic CLI for every migration command.
It configures the async engine from ``app.config.settings`` so that the
database URL is always sourced from the application configuration rather
than being hardcoded in ``alembic.ini``.

Async support follows the pattern described in the SQLAlchemy 2.0 / Alembic
docs:  https://alembic.sqlalchemy.org/en/latest/cookbook.html#using-asyncio-with-alembic

Running concurrently-created indexes
-------------------------------------
Migrations that use ``postgresql_concurrently=True`` **must not** run inside
a transaction.  Set ``transaction_per_migration = False`` at the top of those
migration files so that ``run_migrations_online`` skips the ``BEGIN`` wrapper.
"""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

# ---------------------------------------------------------------------------
# Alembic Config object — provides access to values in alembic.ini.
# ---------------------------------------------------------------------------
config = context.config

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ---------------------------------------------------------------------------
# Import the application settings and model metadata.
# ---------------------------------------------------------------------------
# Import Base here so that autogenerate can detect all mapped tables.
# As models are added to the project they must be imported before this
# module is loaded — the canonical way is to import them in app/models/base.py
# and then import that module below.
# ---------------------------------------------------------------------------
from app.config import settings  # noqa: E402

# ``target_metadata`` will be set to Base.metadata once models exist.
# For now it is ``None`` so that Alembic can still run (no tables to diff).
# Replace with ``from app.models.base import Base; target_metadata = Base.metadata``
# once the initial model layer is added.
target_metadata = None


def _get_url() -> str:
    """Return the database URL from application settings."""
    return settings.database_url


# ---------------------------------------------------------------------------
# Offline migration (--sql flag) — generate SQL without a live connection.
# ---------------------------------------------------------------------------


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    Configures the context with just a URL, without creating an Engine.
    Calls to ``context.execute()`` emit the given string to the script output.
    """
    url = _get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


# ---------------------------------------------------------------------------
# Online migration — run against a live async connection.
# ---------------------------------------------------------------------------


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Create an async engine and run migrations through a synchronous proxy."""
    connectable = create_async_engine(
        _get_url(),
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode (default)."""
    asyncio.run(run_async_migrations())


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
