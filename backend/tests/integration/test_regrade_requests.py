"""Integration tests for regrade-request endpoints.

Covers:
  - POST   /api/v1/grades/{gradeId}/regrade-requests
  - GET    /api/v1/assignments/{assignmentId}/regrade-requests
  - POST   /api/v1/regrade-requests/{requestId}/resolve

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
    db: AsyncSession,
    assignment_id: uuid.UUID,
    class_id: uuid.UUID,
    rubric_id: uuid.UUID,
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
            "content": "Revised essay text.",
            "wc": 3,
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


async def _seed_regrade_request(
    db: AsyncSession,
    request_id: uuid.UUID,
    grade_id: uuid.UUID,
    teacher_id: uuid.UUID,
    *,
    status: str = "open",
) -> None:
    await db.execute(
        text(
            "INSERT INTO regrade_requests "
            "(id, grade_id, teacher_id, dispute_text, status) "
            "VALUES (:id, :gid, :tid, :dt, CAST(:status AS regraderequeststatus)) "
            "ON CONFLICT DO NOTHING"
        ),
        {
            "id": str(request_id),
            "gid": str(grade_id),
            "tid": str(teacher_id),
            "dt": "The score does not reflect the quality of argument presented.",
            "status": status,
        },
    )
    await db.commit()


# ---------------------------------------------------------------------------
# Full scaffold helper
# ---------------------------------------------------------------------------


async def _full_scaffold(
    db: AsyncSession, teacher_id: uuid.UUID
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID]:
    """Seed teacher → class → rubric → assignment → essay → version → grade.

    Returns (assignment_id, essay_id, version_id, grade_id).
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

    return assignment_id, essay_id, version_id, grade_id


# ---------------------------------------------------------------------------
# POST /grades/{gradeId}/regrade-requests
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestCreateRegradeRequestIntegration:
    @pytest.mark.asyncio
    async def test_happy_path_creates_request(self, db_session: AsyncSession, pg_dsn: str) -> None:
        """POST /grades/{id}/regrade-requests creates an open request and returns 201."""
        teacher_id = _uuid()
        _, _, _, grade_id = await _full_scaffold(db_session, teacher_id)

        client = _client_for(teacher_id, pg_dsn)
        resp = client.post(
            f"/api/v1/grades/{grade_id}/regrade-requests",
            json={"dispute_text": "The score does not reflect the evidence presented."},
        )

        assert resp.status_code == 201, resp.text
        body = resp.json()["data"]
        assert body["grade_id"] == str(grade_id)
        assert body["status"] == "open"
        assert body["teacher_id"] == str(teacher_id)

    @pytest.mark.asyncio
    async def test_cross_teacher_grade_returns_403(
        self, db_session: AsyncSession, pg_dsn: str
    ) -> None:
        """Teacher B cannot submit a regrade request for Teacher A's grade."""
        teacher_a = _uuid()
        teacher_b = _uuid()

        await _seed_teacher(db_session, teacher_b)
        _, _, _, grade_id = await _full_scaffold(db_session, teacher_a)

        client = _client_for(teacher_b, pg_dsn)
        resp = client.post(
            f"/api/v1/grades/{grade_id}/regrade-requests",
            json={"dispute_text": "Dispute text from teacher B."},
        )

        assert resp.status_code == 403, resp.text
        assert resp.json()["error"]["code"] == "FORBIDDEN"

    @pytest.mark.asyncio
    async def test_nonexistent_grade_returns_404(
        self, db_session: AsyncSession, pg_dsn: str
    ) -> None:
        teacher_id = _uuid()
        await _seed_teacher(db_session, teacher_id)

        client = _client_for(teacher_id, pg_dsn)
        resp = client.post(
            f"/api/v1/grades/{_uuid()}/regrade-requests",
            json={"dispute_text": "Dispute text."},
        )

        assert resp.status_code == 404, resp.text


# ---------------------------------------------------------------------------
# GET /assignments/{assignmentId}/regrade-requests
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestListRegradeRequestsIntegration:
    @pytest.mark.asyncio
    async def test_happy_path_lists_requests(self, db_session: AsyncSession, pg_dsn: str) -> None:
        """GET returns all regrade requests for an assignment."""
        teacher_id = _uuid()
        request_id = _uuid()

        assignment_id, _, _, grade_id = await _full_scaffold(db_session, teacher_id)
        await _seed_regrade_request(db_session, request_id, grade_id, teacher_id)

        client = _client_for(teacher_id, pg_dsn)
        resp = client.get(f"/api/v1/assignments/{assignment_id}/regrade-requests")

        assert resp.status_code == 200, resp.text
        items = resp.json()["data"]
        assert isinstance(items, list)
        assert any(item["id"] == str(request_id) for item in items)

    @pytest.mark.asyncio
    async def test_cross_teacher_assignment_returns_403(
        self, db_session: AsyncSession, pg_dsn: str
    ) -> None:
        """Teacher B cannot list regrade requests for Teacher A's assignment."""
        teacher_a = _uuid()
        teacher_b = _uuid()

        await _seed_teacher(db_session, teacher_b)
        assignment_id, _, _, _ = await _full_scaffold(db_session, teacher_a)

        client = _client_for(teacher_b, pg_dsn)
        resp = client.get(f"/api/v1/assignments/{assignment_id}/regrade-requests")

        assert resp.status_code == 403, resp.text
        assert resp.json()["error"]["code"] == "FORBIDDEN"

    @pytest.mark.asyncio
    async def test_nonexistent_assignment_returns_404(
        self, db_session: AsyncSession, pg_dsn: str
    ) -> None:
        teacher_id = _uuid()
        await _seed_teacher(db_session, teacher_id)

        client = _client_for(teacher_id, pg_dsn)
        resp = client.get(f"/api/v1/assignments/{_uuid()}/regrade-requests")

        assert resp.status_code == 404, resp.text


# ---------------------------------------------------------------------------
# POST /regrade-requests/{requestId}/resolve
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestResolveRegradeRequestIntegration:
    @pytest.mark.asyncio
    async def test_approve_resolves_request(self, db_session: AsyncSession, pg_dsn: str) -> None:
        """POST /regrade-requests/{id}/resolve with 'approved' updates status."""
        teacher_id = _uuid()
        request_id = _uuid()

        _, _, _, grade_id = await _full_scaffold(db_session, teacher_id)
        await _seed_regrade_request(db_session, request_id, grade_id, teacher_id)

        client = _client_for(teacher_id, pg_dsn)
        resp = client.post(
            f"/api/v1/regrade-requests/{request_id}/resolve",
            json={"resolution": "approved", "resolution_note": "Score has been reviewed."},
        )

        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["status"] == "approved"

    @pytest.mark.asyncio
    async def test_deny_requires_resolution_note(
        self, db_session: AsyncSession, pg_dsn: str
    ) -> None:
        """POST resolve with 'denied' and no resolution_note returns 422."""
        teacher_id = _uuid()
        request_id = _uuid()

        _, _, _, grade_id = await _full_scaffold(db_session, teacher_id)
        await _seed_regrade_request(db_session, request_id, grade_id, teacher_id)

        client = _client_for(teacher_id, pg_dsn)
        resp = client.post(
            f"/api/v1/regrade-requests/{request_id}/resolve",
            json={"resolution": "denied"},
        )

        assert resp.status_code == 422, resp.text

    @pytest.mark.asyncio
    async def test_cross_teacher_request_returns_403(
        self, db_session: AsyncSession, pg_dsn: str
    ) -> None:
        """Teacher B cannot resolve Teacher A's regrade request."""
        teacher_a = _uuid()
        teacher_b = _uuid()
        request_id = _uuid()

        await _seed_teacher(db_session, teacher_b)
        _, _, _, grade_id = await _full_scaffold(db_session, teacher_a)
        await _seed_regrade_request(db_session, request_id, grade_id, teacher_a)

        client = _client_for(teacher_b, pg_dsn)
        resp = client.post(
            f"/api/v1/regrade-requests/{request_id}/resolve",
            json={"resolution": "approved", "resolution_note": "Approved."},
        )

        assert resp.status_code == 403, resp.text
        assert resp.json()["error"]["code"] == "FORBIDDEN"

    @pytest.mark.asyncio
    async def test_nonexistent_request_returns_404(
        self, db_session: AsyncSession, pg_dsn: str
    ) -> None:
        teacher_id = _uuid()
        await _seed_teacher(db_session, teacher_id)

        client = _client_for(teacher_id, pg_dsn)
        resp = client.post(
            f"/api/v1/regrade-requests/{_uuid()}/resolve",
            json={"resolution": "approved", "resolution_note": "Approved."},
        )

        assert resp.status_code == 404, resp.text
