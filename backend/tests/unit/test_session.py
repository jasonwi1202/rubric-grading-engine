"""Unit tests for app.db.session.

Verifies that the session module exports the correct types and that the
get_db dependency yields an AsyncSession.  No live database connection is
required — the engine is not used in these tests.
"""

import ast
import importlib.util

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker


class TestSessionModuleExports:
    """The session module must export the types required by the acceptance criteria."""

    def test_asyncsession_importable(self) -> None:
        from app.db.session import AsyncSession as imported

        assert imported is AsyncSession, f"Expected AsyncSession, got {imported}"

    def test_async_session_local_is_async_sessionmaker(self) -> None:
        from app.db.session import AsyncSessionLocal

        assert isinstance(AsyncSessionLocal, async_sessionmaker), (
            f"AsyncSessionLocal is {type(AsyncSessionLocal)}"
        )

    def test_engine_is_async_engine(self) -> None:
        from app.db.session import engine

        assert isinstance(engine, AsyncEngine), f"engine is {type(engine)}"

    def test_get_db_is_callable(self) -> None:
        from app.db.session import get_db

        assert callable(get_db)


class TestNoSyncImports:
    """session.py must not import from synchronous SQLAlchemy."""

    def test_only_async_sqlalchemy_imported(self) -> None:
        spec = importlib.util.find_spec("app.db.session")
        assert spec is not None
        assert spec.origin is not None

        with open(spec.origin, encoding="utf-8") as fh:
            source = fh.read()

        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module.startswith("sqlalchemy") and not module.startswith(
                    "sqlalchemy.ext.asyncio"
                ):
                    pytest.fail(f"session.py imports from synchronous SQLAlchemy module: {module}")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    module = alias.name
                    if module.startswith("sqlalchemy") and not module.startswith(
                        "sqlalchemy.ext.asyncio"
                    ):
                        pytest.fail(f"session.py imports synchronous SQLAlchemy module: {module}")


class TestGetDbDependency:
    """get_db must yield exactly one AsyncSession per call."""

    @pytest.mark.asyncio
    async def test_get_db_yields_async_session(self) -> None:
        from unittest.mock import AsyncMock, MagicMock, patch

        # Patch AsyncSessionLocal so no real DB connection is made.
        mock_session = AsyncMock(spec=AsyncSession)
        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch("app.db.session.AsyncSessionLocal", return_value=mock_cm):
            from app.db.session import get_db

            yielded: list[object] = []
            async for session in get_db():
                yielded.append(session)

        assert len(yielded) == 1, f"Expected 1 session, got {len(yielded)}"
        assert yielded[0] is mock_session
