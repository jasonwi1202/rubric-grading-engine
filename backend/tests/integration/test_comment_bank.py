"""Integration tests for comment-bank endpoints.

Covers:
  - GET    /api/v1/comment-bank
  - POST   /api/v1/comment-bank
  - DELETE /api/v1/comment-bank/{id}
  - GET    /api/v1/comment-bank/suggestions

Tests run against a real PostgreSQL testcontainer with Alembic migrations.
Auth is injected via FastAPI dependency overrides.

No student PII in fixtures.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.dependencies import get_current_teacher, get_db
from app.main import create_app
from app.models.user import User

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


def _make_teacher_orm(teacher_id: uuid.UUID) -> MagicMock:
    teacher = MagicMock(spec=User)
    teacher.id = teacher_id
    teacher.email = "teacher@school.test"
    teacher.email_verified = True
    teacher.onboarding_complete = True
    return teacher


def _client_for(teacher_id: uuid.UUID, pg_dsn: str) -> TestClient:
    teacher_orm = _make_teacher_orm(teacher_id)
    app = create_app()
    app.dependency_overrides[get_current_teacher] = lambda: teacher_orm

    async def _get_test_db() -> AsyncGenerator[AsyncSession, None]:
        engine = create_async_engine(pg_dsn, echo=False)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            await session.execute(text(f"SET app.current_teacher_id = '{teacher_id}'"))
            yield session
        await engine.dispose()

    app.dependency_overrides[get_db] = _get_test_db
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Seeding helpers
# ---------------------------------------------------------------------------


async def _seed_teacher(db: AsyncSession, teacher_id: uuid.UUID) -> None:
    await db.execute(
        text(
            "INSERT INTO users (id, email, hashed_password, first_name, last_name, "
            "school_name, role, email_verified, onboarding_complete) "
            "VALUES (:id, :email, :pwd, :fn, :ln, :school, 'teacher', true, true) "
            "ON CONFLICT DO NOTHING"
        ),
        {
            "id": str(teacher_id),
            "email": f"teacher-{teacher_id}@test.school",
            "pwd": "x" * 60,
            "fn": "Test",
            "ln": "Teacher",
            "school": "Test School",
        },
    )
    await db.commit()


async def _seed_comment(
    db: AsyncSession,
    comment_id: uuid.UUID,
    teacher_id: uuid.UUID,
    text_: str = "Good use of evidence to support the argument.",
) -> None:
    await db.execute(
        text(
            "INSERT INTO comment_bank_entries (id, teacher_id, text) "
            "VALUES (:id, :tid, :text) ON CONFLICT DO NOTHING"
        ),
        {"id": str(comment_id), "tid": str(teacher_id), "text": text_},
    )
    await db.commit()


# ---------------------------------------------------------------------------
# GET /comment-bank
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestListCommentBankIntegration:
    @pytest.mark.asyncio
    async def test_returns_own_comments_only(self, db_session: AsyncSession, pg_dsn: str) -> None:
        """GET /comment-bank returns only the authenticated teacher's entries.

        Teacher B's comments must not appear in Teacher A's list even when
        both teachers have entries in the database.
        """
        teacher_a = _uuid()
        teacher_b = _uuid()
        comment_a = _uuid()
        comment_b = _uuid()

        await _seed_teacher(db_session, teacher_a)
        await _seed_teacher(db_session, teacher_b)
        await _seed_comment(db_session, comment_a, teacher_a, "Excellent thesis statement.")
        await _seed_comment(db_session, comment_b, teacher_b, "Needs more evidence.")

        client = _client_for(teacher_a, pg_dsn)
        resp = client.get("/api/v1/comment-bank")

        assert resp.status_code == 200, resp.text
        returned_ids = [item["id"] for item in resp.json()["data"]]
        assert str(comment_a) in returned_ids
        assert str(comment_b) not in returned_ids, (
            "Teacher B's comment must not appear in Teacher A's list"
        )

    @pytest.mark.asyncio
    async def test_empty_list_when_no_comments(self, db_session: AsyncSession, pg_dsn: str) -> None:
        """Returns an empty list (not 404) when teacher has no saved comments."""
        teacher_id = _uuid()
        await _seed_teacher(db_session, teacher_id)

        client = _client_for(teacher_id, pg_dsn)
        resp = client.get("/api/v1/comment-bank")

        assert resp.status_code == 200, resp.text
        assert resp.json()["data"] == []


# ---------------------------------------------------------------------------
# POST /comment-bank
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestCreateCommentBankIntegration:
    @pytest.mark.asyncio
    async def test_creates_comment_and_returns_201(
        self, db_session: AsyncSession, pg_dsn: str
    ) -> None:
        """POST /comment-bank creates a new entry scoped to the requesting teacher."""
        teacher_id = _uuid()
        await _seed_teacher(db_session, teacher_id)

        client = _client_for(teacher_id, pg_dsn)
        resp = client.post(
            "/api/v1/comment-bank",
            json={"text": "Consider restructuring the conclusion paragraph."},
        )

        assert resp.status_code == 201, resp.text
        body = resp.json()["data"]
        assert "id" in body
        assert body["text"] == "Consider restructuring the conclusion paragraph."

    @pytest.mark.asyncio
    async def test_created_comment_appears_in_list(
        self, db_session: AsyncSession, pg_dsn: str
    ) -> None:
        """A comment created via POST must appear in the subsequent GET list."""
        teacher_id = _uuid()
        await _seed_teacher(db_session, teacher_id)

        client = _client_for(teacher_id, pg_dsn)
        create_resp = client.post(
            "/api/v1/comment-bank",
            json={"text": "Strong opening hook."},
        )
        assert create_resp.status_code == 201, create_resp.text
        created_id = create_resp.json()["data"]["id"]

        list_resp = client.get("/api/v1/comment-bank")
        assert list_resp.status_code == 200, list_resp.text
        returned_ids = [item["id"] for item in list_resp.json()["data"]]
        assert created_id in returned_ids


# ---------------------------------------------------------------------------
# DELETE /comment-bank/{id}
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestDeleteCommentBankIntegration:
    @pytest.mark.asyncio
    async def test_happy_path_deletes_comment(self, db_session: AsyncSession, pg_dsn: str) -> None:
        """DELETE /comment-bank/{id} returns 204 for the owning teacher."""
        teacher_id = _uuid()
        comment_id = _uuid()

        await _seed_teacher(db_session, teacher_id)
        await _seed_comment(db_session, comment_id, teacher_id)

        client = _client_for(teacher_id, pg_dsn)
        resp = client.delete(f"/api/v1/comment-bank/{comment_id}")

        assert resp.status_code == 204, resp.text

    @pytest.mark.asyncio
    async def test_cross_teacher_comment_returns_403(
        self, db_session: AsyncSession, pg_dsn: str
    ) -> None:
        """Teacher B cannot delete Teacher A's comment bank entry."""
        teacher_a = _uuid()
        teacher_b = _uuid()
        comment_id = _uuid()

        await _seed_teacher(db_session, teacher_a)
        await _seed_teacher(db_session, teacher_b)
        await _seed_comment(db_session, comment_id, teacher_a)

        client = _client_for(teacher_b, pg_dsn)
        resp = client.delete(f"/api/v1/comment-bank/{comment_id}")

        assert resp.status_code == 403, resp.text
        assert resp.json()["error"]["code"] == "FORBIDDEN"

    @pytest.mark.asyncio
    async def test_nonexistent_comment_returns_404(
        self, db_session: AsyncSession, pg_dsn: str
    ) -> None:
        teacher_id = _uuid()
        await _seed_teacher(db_session, teacher_id)

        client = _client_for(teacher_id, pg_dsn)
        resp = client.delete(f"/api/v1/comment-bank/{_uuid()}")

        assert resp.status_code == 404, resp.text


# ---------------------------------------------------------------------------
# GET /comment-bank/suggestions
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestCommentBankSuggestionsIntegration:
    @pytest.mark.asyncio
    async def test_returns_matching_suggestions(
        self, db_session: AsyncSession, pg_dsn: str
    ) -> None:
        """GET /comment-bank/suggestions returns suggestions that match the query."""
        teacher_id = _uuid()
        comment_id = _uuid()

        await _seed_teacher(db_session, teacher_id)
        await _seed_comment(
            db_session, comment_id, teacher_id, "Excellent use of evidence throughout."
        )

        client = _client_for(teacher_id, pg_dsn)
        resp = client.get("/api/v1/comment-bank/suggestions?q=evidence")

        assert resp.status_code == 200, resp.text
        items = resp.json()["data"]
        assert isinstance(items, list)
        # The seeded comment mentions "evidence" so it should appear.
        assert any(item["id"] == str(comment_id) for item in items)

    @pytest.mark.asyncio
    async def test_suggestions_do_not_expose_another_teachers_comments(
        self, db_session: AsyncSession, pg_dsn: str
    ) -> None:
        """Suggestions endpoint must only return the requesting teacher's comments."""
        teacher_a = _uuid()
        teacher_b = _uuid()
        comment_b = _uuid()

        await _seed_teacher(db_session, teacher_a)
        await _seed_teacher(db_session, teacher_b)
        # Teacher B has a comment that would match the query "thesis".
        await _seed_comment(db_session, comment_b, teacher_b, "Strong thesis statement overall.")

        client = _client_for(teacher_a, pg_dsn)
        resp = client.get("/api/v1/comment-bank/suggestions?q=thesis")

        assert resp.status_code == 200, resp.text
        returned_ids = [item["id"] for item in resp.json()["data"]]
        assert str(comment_b) not in returned_ids, (
            "Teacher B's comment must not appear in Teacher A's suggestions"
        )
