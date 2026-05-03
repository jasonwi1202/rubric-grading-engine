"""Integration tests for integrity-report endpoints.

Covers:
  - GET    /api/v1/essays/{essayId}/integrity
  - GET    /api/v1/assignments/{assignmentId}/integrity/summary
  - PATCH  /api/v1/integrity-reports/{reportId}/status

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
            "content": "Test essay text for integrity check.",
            "wc": 7,
        },
    )
    await db.commit()


async def _seed_integrity_report(
    db: AsyncSession,
    report_id: uuid.UUID,
    version_id: uuid.UUID,
    teacher_id: uuid.UUID,
    *,
    status: str = "pending",
) -> None:
    await db.execute(
        text(
            "INSERT INTO integrity_reports "
            "(id, essay_version_id, teacher_id, provider, ai_likelihood, "
            "similarity_score, flagged_passages, status) "
            "VALUES (:id, :vid, :tid, :provider, :ai_lh, :sim, NULL, CAST(:status AS integritystatus)) "
            "ON CONFLICT DO NOTHING"
        ),
        {
            "id": str(report_id),
            "vid": str(version_id),
            "tid": str(teacher_id),
            "provider": "gptzero",
            "ai_lh": 0.12,
            "sim": 0.05,
            "status": status,
        },
    )
    await db.commit()


# ---------------------------------------------------------------------------
# Full scaffold helper
# ---------------------------------------------------------------------------


async def _full_scaffold(
    db: AsyncSession,
    teacher_id: uuid.UUID,
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID]:
    """Seed teacher → class → rubric → assignment → essay → essay_version.

    Returns (class_id, assignment_id, essay_id, version_id, rubric_id).
    """
    class_id = _uuid()
    rubric_id = _uuid()
    assignment_id = _uuid()
    essay_id = _uuid()
    version_id = _uuid()

    await _seed_teacher(db, teacher_id)
    await _seed_class(db, class_id, teacher_id)
    await _seed_rubric(db, rubric_id, teacher_id)
    await _seed_assignment(db, assignment_id, class_id, rubric_id)
    await _seed_essay(db, essay_id, assignment_id)
    await _seed_essay_version(db, version_id, essay_id)

    return class_id, assignment_id, essay_id, version_id, rubric_id


# ---------------------------------------------------------------------------
# GET /essays/{essayId}/integrity
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestGetEssayIntegrityIntegration:
    @pytest.mark.asyncio
    async def test_happy_path_returns_integrity_report(
        self, db_session: AsyncSession, pg_dsn: str
    ) -> None:
        """GET /essays/{id}/integrity returns the integrity report for the owning teacher."""
        teacher_id = _uuid()
        report_id = _uuid()

        _, _, essay_id, version_id, _ = await _full_scaffold(db_session, teacher_id)
        await _seed_integrity_report(db_session, report_id, version_id, teacher_id)

        client = _client_for(teacher_id, pg_dsn)
        resp = client.get(f"/api/v1/essays/{essay_id}/integrity")

        assert resp.status_code == 200, resp.text
        body = resp.json()["data"]
        assert body["id"] == str(report_id)
        assert body["provider"] == "gptzero"
        assert body["status"] == "pending"

    @pytest.mark.asyncio
    async def test_cross_teacher_essay_returns_403(
        self, db_session: AsyncSession, pg_dsn: str
    ) -> None:
        """Teacher B cannot read integrity report for Teacher A's essay."""
        teacher_a = _uuid()
        teacher_b = _uuid()
        report_id = _uuid()

        await _seed_teacher(db_session, teacher_b)
        _, _, essay_id, version_id, _ = await _full_scaffold(db_session, teacher_a)
        await _seed_integrity_report(db_session, report_id, version_id, teacher_a)

        client = _client_for(teacher_b, pg_dsn)
        resp = client.get(f"/api/v1/essays/{essay_id}/integrity")

        assert resp.status_code == 403, resp.text
        assert resp.json()["error"]["code"] == "FORBIDDEN"

    @pytest.mark.asyncio
    async def test_nonexistent_essay_returns_404(
        self, db_session: AsyncSession, pg_dsn: str
    ) -> None:
        teacher_id = _uuid()
        await _seed_teacher(db_session, teacher_id)

        client = _client_for(teacher_id, pg_dsn)
        resp = client.get(f"/api/v1/essays/{_uuid()}/integrity")

        assert resp.status_code == 404, resp.text

    @pytest.mark.asyncio
    async def test_essay_with_no_report_returns_404(
        self, db_session: AsyncSession, pg_dsn: str
    ) -> None:
        """Essay exists but has no integrity report → 404."""
        teacher_id = _uuid()
        _, _, essay_id, _, _ = await _full_scaffold(db_session, teacher_id)

        client = _client_for(teacher_id, pg_dsn)
        resp = client.get(f"/api/v1/essays/{essay_id}/integrity")

        assert resp.status_code == 404, resp.text


# ---------------------------------------------------------------------------
# GET /assignments/{assignmentId}/integrity/summary
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestGetAssignmentIntegritySummaryIntegration:
    @pytest.mark.asyncio
    async def test_happy_path_returns_summary(self, db_session: AsyncSession, pg_dsn: str) -> None:
        """Returns aggregate integrity counts for the owning teacher's assignment."""
        teacher_id = _uuid()
        report_id = _uuid()

        _, assignment_id, _, version_id, _ = await _full_scaffold(db_session, teacher_id)
        await _seed_integrity_report(db_session, report_id, version_id, teacher_id)

        client = _client_for(teacher_id, pg_dsn)
        resp = client.get(f"/api/v1/assignments/{assignment_id}/integrity/summary")

        assert resp.status_code == 200, resp.text
        body = resp.json()["data"]
        # The response shape uses plain status names as keys: pending, flagged, reviewed_clear.
        assert "pending" in body or "flagged" in body or "reviewed_clear" in body

    @pytest.mark.asyncio
    async def test_cross_teacher_assignment_returns_403(
        self, db_session: AsyncSession, pg_dsn: str
    ) -> None:
        """Teacher B cannot read integrity summary for Teacher A's assignment."""
        teacher_a = _uuid()
        teacher_b = _uuid()

        await _seed_teacher(db_session, teacher_b)
        _, assignment_id, _, _, _ = await _full_scaffold(db_session, teacher_a)

        client = _client_for(teacher_b, pg_dsn)
        resp = client.get(f"/api/v1/assignments/{assignment_id}/integrity/summary")

        assert resp.status_code == 403, resp.text
        assert resp.json()["error"]["code"] == "FORBIDDEN"

    @pytest.mark.asyncio
    async def test_nonexistent_assignment_returns_404(
        self, db_session: AsyncSession, pg_dsn: str
    ) -> None:
        teacher_id = _uuid()
        await _seed_teacher(db_session, teacher_id)

        client = _client_for(teacher_id, pg_dsn)
        resp = client.get(f"/api/v1/assignments/{_uuid()}/integrity/summary")

        assert resp.status_code == 404, resp.text


# ---------------------------------------------------------------------------
# PATCH /integrity-reports/{reportId}/status
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestPatchIntegrityStatusIntegration:
    @pytest.mark.asyncio
    async def test_happy_path_updates_status(self, db_session: AsyncSession, pg_dsn: str) -> None:
        """PATCH /integrity-reports/{id}/status transitions to reviewed_clear."""
        teacher_id = _uuid()
        report_id = _uuid()

        _, _, _, version_id, _ = await _full_scaffold(db_session, teacher_id)
        await _seed_integrity_report(db_session, report_id, version_id, teacher_id)

        client = _client_for(teacher_id, pg_dsn)
        resp = client.patch(
            f"/api/v1/integrity-reports/{report_id}/status",
            json={"status": "reviewed_clear"},
        )

        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["status"] == "reviewed_clear"

    @pytest.mark.asyncio
    async def test_cross_teacher_report_returns_403(
        self, db_session: AsyncSession, pg_dsn: str
    ) -> None:
        """Teacher B cannot update the status of Teacher A's integrity report."""
        teacher_a = _uuid()
        teacher_b = _uuid()
        report_id = _uuid()

        await _seed_teacher(db_session, teacher_b)
        _, _, _, version_id, _ = await _full_scaffold(db_session, teacher_a)
        await _seed_integrity_report(db_session, report_id, version_id, teacher_a)

        client = _client_for(teacher_b, pg_dsn)
        resp = client.patch(
            f"/api/v1/integrity-reports/{report_id}/status",
            json={"status": "reviewed_clear"},
        )

        assert resp.status_code == 403, resp.text
        assert resp.json()["error"]["code"] == "FORBIDDEN"

    @pytest.mark.asyncio
    async def test_nonexistent_report_returns_404(
        self, db_session: AsyncSession, pg_dsn: str
    ) -> None:
        teacher_id = _uuid()
        await _seed_teacher(db_session, teacher_id)

        client = _client_for(teacher_id, pg_dsn)
        resp = client.patch(
            f"/api/v1/integrity-reports/{_uuid()}/status",
            json={"status": "reviewed_clear"},
        )

        assert resp.status_code == 404, resp.text
