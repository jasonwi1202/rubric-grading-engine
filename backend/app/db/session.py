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
