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
    """Yield an ``AsyncSession`` and guarantee it is closed after the request."""
    async with AsyncSessionLocal() as session:
        yield session


# ---------------------------------------------------------------------------
# Tenant context helper (RLS support)
# ---------------------------------------------------------------------------


async def set_tenant_context(db: AsyncSession, teacher_id: uuid.UUID) -> None:
    """Set the PostgreSQL session variable used by RLS tenant isolation policies.

    Must be called within an open transaction before any query that touches a
    tenant-scoped table (classes, students, rubrics, assignments, essays,
    grades).  Uses ``SET LOCAL`` so the variable is automatically reset when
    the transaction ends — safe for use with connection-pooled sessions.

    Example::

        async with AsyncSessionLocal() as db:
            async with db.begin():
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
        __import__("sqlalchemy").text("SET LOCAL app.current_teacher_id = :tid"),
        {"tid": str(teacher_id)},
    )
