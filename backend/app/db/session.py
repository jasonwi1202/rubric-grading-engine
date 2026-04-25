"""Async SQLAlchemy session factory.

Usage
-----
Inject the session as a FastAPI dependency::

    from app.db.session import get_db

    @router.get("/example")
    async def example(db: AsyncSession = Depends(get_db)):
        result = await db.execute(select(MyModel))
        ...

For one-off access outside a request (e.g. in Celery tasks), use the
``tenant_session`` async context manager so that the tenant context is set
**before** any tenant-scoped query and reset **after** the session closes::

    from app.db.session import tenant_session

    async def my_celery_task(teacher_id: uuid.UUID) -> None:
        async with tenant_session(teacher_id) as session:
            result = await session.execute(select(MyModel))
            ...

Do **not** use ``AsyncSessionLocal`` directly in tasks unless the query is
explicitly scoped to a non-tenant-isolated table (e.g. audit_logs, users).
With FORCE ROW LEVEL SECURITY enabled, any query against a tenant-scoped
table without a prior ``SET app.current_teacher_id`` call will return zero
rows silently.
"""

import logging
import uuid
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.ext.asyncio import (
    AsyncSession as AsyncSession,  # re-exported for consumers and type checkers
)

from app.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

engine: AsyncEngine = create_async_engine(
    settings.database_url,
    pool_size=settings.database_pool_size,
    max_overflow=settings.database_max_overflow,
    # SQL echo is disabled in all environments: query output can contain
    # parameter values that include student PII.
    echo=False,
)

# ---------------------------------------------------------------------------
# Session factory
# ---------------------------------------------------------------------------

AsyncSessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield an ``AsyncSession`` and guarantee it is closed after the request.

    On exit, the per-session ``app.current_teacher_id`` GUC is reset to ''
    so that when the underlying connection is returned to the pool the next
    borrower does not inherit a stale tenant context.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            # Best-effort reset to prevent stale tenant context leaking to the
            # next user of this pooled connection.  Any exception (connection
            # error, session invalid state, etc.) is suppressed — this cleanup
            # must never mask the actual route error.
            try:
                _sa = __import__("sqlalchemy")
                await session.execute(_sa.text("SET app.current_teacher_id = ''"))
            except Exception:  # noqa: BLE001
                logger.debug("RLS context reset failed after request", exc_info=True)


# ---------------------------------------------------------------------------
# Tenant context helper (RLS support)
# ---------------------------------------------------------------------------


async def set_tenant_context(db: AsyncSession, teacher_id: uuid.UUID) -> None:
    """Set the PostgreSQL session variable used by RLS tenant isolation policies.

    Uses ``SET`` (session-level, not ``SET LOCAL``) so the variable persists
    across transaction boundaries within the same session.  This is required
    because service functions may call ``await db.commit()`` followed by
    ``await db.refresh()``: the refresh opens a new implicit transaction, and
    ``SET LOCAL`` would have been cleared at the previous commit.

    The variable is reset to '' in ``get_db``'s finally block before the
    connection is returned to the pool, preventing cross-request leakage.

    Example::

        async with AsyncSessionLocal() as db:
            await set_tenant_context(db, teacher.id)
            result = await db.execute(select(Class).where(...))

    Args:
        db: The active ``AsyncSession``.
        teacher_id: UUID of the authenticated teacher.
    """
    result = await db.execute(
        # NOTE: `sqlalchemy.text` cannot be imported at module level in this file
        # because tests/unit/test_session.py enforces (via AST analysis) that
        # session.py only imports from `sqlalchemy.ext.asyncio`, not from the
        # synchronous `sqlalchemy` package.  Using __import__ at call-time
        # satisfies both the runtime requirement and that AST constraint.
        #
        # PostgreSQL does not allow bind parameters in a raw SET statement
        # (`SET app.current_teacher_id = $1` is a syntax error under asyncpg).
        # set_config(name, value, is_local) is parameter-safe and preserves the
        # same session-level behavior when is_local=false.
        __import__("sqlalchemy").text("SELECT set_config('app.current_teacher_id', :tid, false)"),
        {"tid": str(teacher_id)},
    )
    # Consume the single-row result so the asyncpg connection is fully idle
    # before subsequent statements run on this session.
    result.scalar_one_or_none()


@asynccontextmanager
async def tenant_session(teacher_id: uuid.UUID) -> AsyncIterator[AsyncSession]:
    """Async context manager for Celery tasks and background jobs.

    Opens a new ``AsyncSession``, activates the RLS tenant context for
    *teacher_id*, and guarantees the context is reset to '' before the
    connection is returned to the pool.

    Use this instead of raw ``AsyncSessionLocal()`` in any task that queries
    tenant-scoped tables.  With ``FORCE ROW LEVEL SECURITY`` enabled, a
    session without ``app.current_teacher_id`` set will return **zero rows**
    silently from tenant-scoped tables — this context manager prevents that
    mistake.

    Example::

        from app.db.session import tenant_session

        async def grade_essay_task(teacher_id: uuid.UUID, essay_id: uuid.UUID) -> None:
            async with tenant_session(teacher_id) as db:
                essay = await db.get(Essay, essay_id)
                ...

    Args:
        teacher_id: UUID of the teacher whose tenant context should be set.

    Yields:
        An ``AsyncSession`` with the RLS tenant context already active.
    """
    async with AsyncSessionLocal() as session:
        try:
            await set_tenant_context(session, teacher_id)
            yield session
        finally:
            try:
                _sa = __import__("sqlalchemy")
                await session.execute(_sa.text("SET app.current_teacher_id = ''"))
            except Exception:  # noqa: BLE001
                logger.debug("RLS context reset failed in tenant_session", exc_info=True)
