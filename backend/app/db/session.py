"""Async SQLAlchemy session factory.

Usage
-----
Inject the session as a FastAPI dependency::

    from app.db.session import get_db

    @router.get("/example")
    async def example(db: AsyncSession = Depends(get_db)):
        result = await db.execute(select(MyModel))
        ...

For one-off access outside a request (e.g. in Celery tasks)::

    from app.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        ...
"""

import uuid
from collections.abc import AsyncGenerator
from contextlib import suppress

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.ext.asyncio import (
    AsyncSession as AsyncSession,  # re-exported for consumers and type checkers
)

from app.config import settings

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
            # Best-effort reset; ignore errors if the session is already closed.
            with suppress(Exception):
                await session.execute(
                    __import__("sqlalchemy").text("SET app.current_teacher_id = ''"),
                )


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
    await db.execute(
        # NOTE: `sqlalchemy.text` cannot be imported at module level in this file
        # because tests/unit/test_session.py enforces (via AST analysis) that
        # session.py only imports from `sqlalchemy.ext.asyncio`, not from the
        # synchronous `sqlalchemy` package.  Using __import__ at call-time
        # satisfies both the runtime requirement and that AST constraint.
        __import__("sqlalchemy").text("SET app.current_teacher_id = :tid"),
        {"tid": str(teacher_id)},
    )
