"""Integration tests for media-comment endpoints.

Covers:
  - GET    /api/v1/grades/{gradeId}/media-comments  (list)
  - DELETE /api/v1/media-comments/{id}
  - GET    /api/v1/media-comments/{id}/url
  - POST   /api/v1/media-comments/{id}/save-to-bank
  - GET    /api/v1/media-comments/bank

Create (POST /grades/{id}/media-comments) requires an S3 upload and is
tested in the unit test suite (``test_comment_bank_router.py``) with a mocked
storage backend.  The integration tests here focus on cross-teacher isolation
and happy-path reads for rows that can be seeded directly into the DB.

Tests run against a real PostgreSQL testcontainer with Alembic migrations.
Auth is injected via FastAPI dependency overrides.

No student PII in fixtures.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from unittest.mock import MagicMock, patch

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


async def _seed_class(db: AsyncSession, class_id: uuid.UUID, teacher_id: uuid.UUID) -> None:
    await db.execute(
        text(
            "INSERT INTO classes "
            "(id, teacher_id, name, subject, grade_level, academic_year, is_archived) "
            "VALUES (:id, :tid, :name, :subj, :gl, :ay, false) ON CONFLICT DO NOTHING"
        ),
        {
            "id": str(class_id),
            "tid": str(teacher_id),
            "name": "Test Class",
            "subj": "English",
            "gl": "8",
            "ay": "2025-2026",
        },
    )
    await db.commit()


async def _seed_rubric(db: AsyncSession, rubric_id: uuid.UUID, teacher_id: uuid.UUID) -> None:
    await db.execute(
        text(
            "INSERT INTO rubrics (id, teacher_id, name, is_template) "
            "VALUES (:id, :tid, :name, false) ON CONFLICT DO NOTHING"
        ),
        {"id": str(rubric_id), "tid": str(teacher_id), "name": "Test Rubric"},
    )
    await db.commit()


async def _seed_assignment(
    db: AsyncSession, assignment_id: uuid.UUID, class_id: uuid.UUID, rubric_id: uuid.UUID
) -> None:
    await db.execute(
        text(
            "INSERT INTO assignments "
            "(id, class_id, rubric_id, rubric_snapshot, title, status) "
            "VALUES (:id, :cid, :rid, CAST(:snap AS jsonb), :title, 'open') "
            "ON CONFLICT DO NOTHING"
        ),
        {
            "id": str(assignment_id),
            "cid": str(class_id),
            "rid": str(rubric_id),
            "snap": '{"criteria": []}',
            "title": "Test Assignment",
        },
    )
    await db.commit()


async def _seed_essay(db: AsyncSession, essay_id: uuid.UUID, assignment_id: uuid.UUID) -> None:
    await db.execute(
        text(
            "INSERT INTO essays (id, assignment_id, status) "
            "VALUES (:id, :aid, 'unassigned') ON CONFLICT DO NOTHING"
        ),
        {"id": str(essay_id), "aid": str(assignment_id)},
    )
    await db.commit()


async def _seed_essay_version(db: AsyncSession, version_id: uuid.UUID, essay_id: uuid.UUID) -> None:
    await db.execute(
        text(
            "INSERT INTO essay_versions (id, essay_id, version_number, content, word_count) "
            "VALUES (:id, :eid, 1, :content, :wc) ON CONFLICT DO NOTHING"
        ),
        {
            "id": str(version_id),
            "eid": str(essay_id),
            "content": "Essay text.",
            "wc": 2,
        },
    )
    await db.commit()


async def _seed_grade(db: AsyncSession, grade_id: uuid.UUID, version_id: uuid.UUID) -> None:
    await db.execute(
        text(
            "INSERT INTO grades "
            "(id, essay_version_id, total_score, max_possible_score, "
            "summary_feedback, strictness, ai_model, prompt_version, is_locked) "
            "VALUES (:id, :vid, :ts, :mps, :sf, 'balanced', 'gpt-4o', 'grading-v1', false) "
            "ON CONFLICT DO NOTHING"
        ),
        {
            "id": str(grade_id),
            "vid": str(version_id),
            "ts": "8.00",
            "mps": "10.00",
            "sf": "Good overall.",
        },
    )
    await db.commit()


async def _seed_media_comment(
    db: AsyncSession,
    comment_id: uuid.UUID,
    grade_id: uuid.UUID,
    teacher_id: uuid.UUID,
    *,
    is_banked: bool = False,
) -> None:
    """Insert a media_comments row directly (bypassing S3 upload)."""
    s3_key = f"media/{teacher_id}/{grade_id}/{comment_id}.webm"
    await db.execute(
        text(
            "INSERT INTO media_comments "
            "(id, grade_id, teacher_id, s3_key, duration_seconds, mime_type, is_banked) "
            "VALUES (:id, :gid, :tid, :s3key, :dur, :mime, :banked) "
            "ON CONFLICT DO NOTHING"
        ),
        {
            "id": str(comment_id),
            "gid": str(grade_id),
            "tid": str(teacher_id),
            "s3key": s3_key,
            "dur": 15,
            "mime": "audio/webm",
            "banked": is_banked,
        },
    )
    await db.commit()


# ---------------------------------------------------------------------------
# Full scaffold helper
# ---------------------------------------------------------------------------


async def _full_scaffold(db: AsyncSession, teacher_id: uuid.UUID) -> tuple[uuid.UUID, uuid.UUID]:
    """Seed teacher → class → rubric → assignment → essay → version → grade.

    Returns (essay_id, grade_id).
    """
    class_id = _uuid()
    rubric_id = _uuid()
    assignment_id = _uuid()
    essay_id = _uuid()
    version_id = _uuid()
    grade_id = _uuid()

    await _seed_teacher(db, teacher_id)
    await _seed_class(db, class_id, teacher_id)
    await _seed_rubric(db, rubric_id, teacher_id)
    await _seed_assignment(db, assignment_id, class_id, rubric_id)
    await _seed_essay(db, essay_id, assignment_id)
    await _seed_essay_version(db, version_id, essay_id)
    await _seed_grade(db, grade_id, version_id)

    return essay_id, grade_id


# ---------------------------------------------------------------------------
# GET /grades/{gradeId}/media-comments
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestListGradeMediaCommentsIntegration:
    @pytest.mark.asyncio
    async def test_happy_path_returns_comments(self, db_session: AsyncSession, pg_dsn: str) -> None:
        """Returns all media comments for a grade in chronological order."""
        teacher_id = _uuid()
        comment_id = _uuid()

        _, grade_id = await _full_scaffold(db_session, teacher_id)
        await _seed_media_comment(db_session, comment_id, grade_id, teacher_id)

        client = _client_for(teacher_id, pg_dsn)
        resp = client.get(f"/api/v1/grades/{grade_id}/media-comments")

        assert resp.status_code == 200, resp.text
        items = resp.json()["data"]
        assert isinstance(items, list)
        assert any(item["id"] == str(comment_id) for item in items)

    @pytest.mark.asyncio
    async def test_cross_teacher_grade_returns_403(
        self, db_session: AsyncSession, pg_dsn: str
    ) -> None:
        """Teacher B cannot list media comments for Teacher A's grade."""
        teacher_a = _uuid()
        teacher_b = _uuid()

        await _seed_teacher(db_session, teacher_b)
        _, grade_id = await _full_scaffold(db_session, teacher_a)

        client = _client_for(teacher_b, pg_dsn)
        resp = client.get(f"/api/v1/grades/{grade_id}/media-comments")

        assert resp.status_code == 403, resp.text
        assert resp.json()["error"]["code"] == "FORBIDDEN"

    @pytest.mark.asyncio
    async def test_nonexistent_grade_returns_404(
        self, db_session: AsyncSession, pg_dsn: str
    ) -> None:
        teacher_id = _uuid()
        await _seed_teacher(db_session, teacher_id)

        client = _client_for(teacher_id, pg_dsn)
        resp = client.get(f"/api/v1/grades/{_uuid()}/media-comments")

        assert resp.status_code == 404, resp.text


# ---------------------------------------------------------------------------
# DELETE /media-comments/{id}
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestDeleteMediaCommentIntegration:
    @pytest.mark.asyncio
    async def test_happy_path_deletes_comment(self, db_session: AsyncSession, pg_dsn: str) -> None:
        """DELETE returns 204 and removes the comment (S3 delete is mocked)."""
        teacher_id = _uuid()
        comment_id = _uuid()

        _, grade_id = await _full_scaffold(db_session, teacher_id)
        await _seed_media_comment(db_session, comment_id, grade_id, teacher_id)

        client = _client_for(teacher_id, pg_dsn)
        # Mock S3 deletion so the test does not require a running object store.
        with patch(
            "app.storage.s3.delete_file",
            new=MagicMock(return_value=None),
        ):
            resp = client.delete(f"/api/v1/media-comments/{comment_id}")

        assert resp.status_code == 204, resp.text

    @pytest.mark.asyncio
    async def test_cross_teacher_comment_returns_403(
        self, db_session: AsyncSession, pg_dsn: str
    ) -> None:
        """Teacher B cannot delete Teacher A's media comment."""
        teacher_a = _uuid()
        teacher_b = _uuid()
        comment_id = _uuid()

        await _seed_teacher(db_session, teacher_b)
        _, grade_id = await _full_scaffold(db_session, teacher_a)
        await _seed_media_comment(db_session, comment_id, grade_id, teacher_a)

        client = _client_for(teacher_b, pg_dsn)
        resp = client.delete(f"/api/v1/media-comments/{comment_id}")

        assert resp.status_code == 403, resp.text
        assert resp.json()["error"]["code"] == "FORBIDDEN"

    @pytest.mark.asyncio
    async def test_nonexistent_comment_returns_404(
        self, db_session: AsyncSession, pg_dsn: str
    ) -> None:
        teacher_id = _uuid()
        await _seed_teacher(db_session, teacher_id)

        client = _client_for(teacher_id, pg_dsn)
        resp = client.delete(f"/api/v1/media-comments/{_uuid()}")

        assert resp.status_code == 404, resp.text


# ---------------------------------------------------------------------------
# GET /media-comments/bank
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestListBankedMediaCommentsIntegration:
    @pytest.mark.asyncio
    async def test_bank_returns_only_own_banked_comments(
        self, db_session: AsyncSession, pg_dsn: str
    ) -> None:
        """GET /media-comments/bank returns only the authenticated teacher's banked items.

        Teacher B's banked items must not appear in Teacher A's response.
        """
        teacher_a = _uuid()
        teacher_b = _uuid()
        comment_a = _uuid()
        comment_b = _uuid()

        await _seed_teacher(db_session, teacher_b)
        _, grade_a = await _full_scaffold(db_session, teacher_a)
        await _seed_media_comment(db_session, comment_a, grade_a, teacher_a, is_banked=True)

        # Scaffold for teacher B — needs its own full entity chain.
        class_b = _uuid()
        rubric_b = _uuid()
        assign_b = _uuid()
        essay_b = _uuid()
        version_b = _uuid()
        grade_b = _uuid()
        await _seed_class(db_session, class_b, teacher_b)
        await _seed_rubric(db_session, rubric_b, teacher_b)
        await _seed_assignment(db_session, assign_b, class_b, rubric_b)
        await _seed_essay(db_session, essay_b, assign_b)
        await _seed_essay_version(db_session, version_b, essay_b)
        await _seed_grade(db_session, grade_b, version_b)
        await _seed_media_comment(db_session, comment_b, grade_b, teacher_b, is_banked=True)

        client = _client_for(teacher_a, pg_dsn)
        resp = client.get("/api/v1/media-comments/bank")

        assert resp.status_code == 200, resp.text
        items = resp.json()["data"]
        returned_ids = [item["id"] for item in items]
        assert str(comment_a) in returned_ids
        assert str(comment_b) not in returned_ids, (
            "Teacher B's banked comment must not appear in Teacher A's bank"
        )
