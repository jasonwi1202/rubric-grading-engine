"""Integration tests for intervention recommendation endpoints (M7-01).

Covers:
  - GET    /api/v1/interventions
  - POST   /api/v1/interventions/{id}/approve
  - DELETE /api/v1/interventions/{id}

Tests run against a real PostgreSQL testcontainer with Alembic migrations.
Auth is injected via FastAPI dependency overrides.

No student PII in fixtures.
"""

from __future__ import annotations

import json
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
    """Return a TestClient with auth and DB overridden for the given teacher."""
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


async def _seed_student(db: AsyncSession, student_id: uuid.UUID, teacher_id: uuid.UUID) -> None:
    await db.execute(
        text(
            "INSERT INTO students (id, teacher_id, full_name) "
            "VALUES (:id, :tid, :name) ON CONFLICT DO NOTHING"
        ),
        {"id": str(student_id), "tid": str(teacher_id), "name": "Student A"},
    )
    await db.commit()


async def _seed_intervention(
    db: AsyncSession,
    rec_id: uuid.UUID,
    teacher_id: uuid.UUID,
    student_id: uuid.UUID,
    *,
    status: str = "pending_review",
) -> None:
    await db.execute(
        text(
            "INSERT INTO intervention_recommendations "
            "(id, teacher_id, student_id, trigger_type, skill_key, urgency, "
            "trigger_reason, evidence_summary, suggested_action, details, status) "
            "VALUES (:id, :tid, :sid, :tt, :sk, :urg, :tr, :es, :sa, CAST(:det AS jsonb), :st)"
        ),
        {
            "id": str(rec_id),
            "tid": str(teacher_id),
            "sid": str(student_id),
            "tt": "persistent_gap",
            "sk": "evidence",
            "urg": 3,
            "tr": "Skill evidence is persistently below threshold.",
            "es": "Average score is below threshold across recent assignments.",
            "sa": "Assign evidence-focused writing practice.",
            "det": json.dumps({"avg_score": 0.42, "trend": "stable", "assignment_count": 3}),
            "st": status,
        },
    )
    await db.commit()


@pytest.mark.integration
class TestInterventionListIntegration:
    @pytest.mark.asyncio
    async def test_default_list_returns_pending_only(
        self, db_session: AsyncSession, pg_dsn: str
    ) -> None:
        teacher_id = _uuid()
        student_id = _uuid()
        pending_id = _uuid()
        approved_id = _uuid()

        await _seed_teacher(db_session, teacher_id)
        await _seed_student(db_session, student_id, teacher_id)
        await _seed_intervention(
            db_session, pending_id, teacher_id, student_id, status="pending_review"
        )
        await _seed_intervention(db_session, approved_id, teacher_id, student_id, status="approved")

        client = _client_for(teacher_id, pg_dsn)
        resp = client.get("/api/v1/interventions")

        assert resp.status_code == 200, resp.text
        body = resp.json()["data"]
        assert body["total_count"] == 1
        assert len(body["items"]) == 1
        assert body["items"][0]["id"] == str(pending_id)
        assert body["items"][0]["status"] == "pending_review"

    @pytest.mark.asyncio
    async def test_status_all_returns_historical_items(
        self, db_session: AsyncSession, pg_dsn: str
    ) -> None:
        teacher_id = _uuid()
        student_id = _uuid()

        await _seed_teacher(db_session, teacher_id)
        await _seed_student(db_session, student_id, teacher_id)
        await _seed_intervention(
            db_session, _uuid(), teacher_id, student_id, status="pending_review"
        )
        await _seed_intervention(db_session, _uuid(), teacher_id, student_id, status="dismissed")

        client = _client_for(teacher_id, pg_dsn)
        resp = client.get("/api/v1/interventions?status=all")

        assert resp.status_code == 200, resp.text
        body = resp.json()["data"]
        assert body["total_count"] == 2
        statuses = {item["status"] for item in body["items"]}
        assert statuses == {"pending_review", "dismissed"}


@pytest.mark.integration
class TestInterventionActionIntegration:
    @pytest.mark.asyncio
    async def test_approve_sets_status_and_writes_audit(
        self, db_session: AsyncSession, pg_dsn: str
    ) -> None:
        teacher_id = _uuid()
        student_id = _uuid()
        rec_id = _uuid()

        await _seed_teacher(db_session, teacher_id)
        await _seed_student(db_session, student_id, teacher_id)
        await _seed_intervention(
            db_session, rec_id, teacher_id, student_id, status="pending_review"
        )

        client = _client_for(teacher_id, pg_dsn)
        resp = client.post(f"/api/v1/interventions/{rec_id}/approve")

        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["status"] == "approved"

        status_result = await db_session.execute(
            text("SELECT status FROM intervention_recommendations WHERE id = :id"),
            {"id": str(rec_id)},
        )
        assert status_result.scalar_one() == "approved"

        audit_result = await db_session.execute(
            text(
                "SELECT count(*) FROM audit_logs "
                "WHERE entity_type = 'intervention_recommendation' "
                "AND entity_id = :id "
                "AND action = 'intervention_recommendation.approved'"
            ),
            {"id": str(rec_id)},
        )
        assert audit_result.scalar_one() == 1

    @pytest.mark.asyncio
    async def test_dismiss_sets_status_and_writes_audit(
        self, db_session: AsyncSession, pg_dsn: str
    ) -> None:
        teacher_id = _uuid()
        student_id = _uuid()
        rec_id = _uuid()

        await _seed_teacher(db_session, teacher_id)
        await _seed_student(db_session, student_id, teacher_id)
        await _seed_intervention(
            db_session, rec_id, teacher_id, student_id, status="pending_review"
        )

        client = _client_for(teacher_id, pg_dsn)
        resp = client.delete(f"/api/v1/interventions/{rec_id}")

        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["status"] == "dismissed"

        status_result = await db_session.execute(
            text("SELECT status FROM intervention_recommendations WHERE id = :id"),
            {"id": str(rec_id)},
        )
        assert status_result.scalar_one() == "dismissed"

        audit_result = await db_session.execute(
            text(
                "SELECT count(*) FROM audit_logs "
                "WHERE entity_type = 'intervention_recommendation' "
                "AND entity_id = :id "
                "AND action = 'intervention_recommendation.dismissed'"
            ),
            {"id": str(rec_id)},
        )
        assert audit_result.scalar_one() == 1

    @pytest.mark.asyncio
    async def test_cross_teacher_approve_returns_404(
        self, db_session: AsyncSession, pg_dsn: str
    ) -> None:
        teacher_a = _uuid()
        teacher_b = _uuid()
        student_id = _uuid()
        rec_id = _uuid()

        await _seed_teacher(db_session, teacher_a)
        await _seed_teacher(db_session, teacher_b)
        await _seed_student(db_session, student_id, teacher_a)
        await _seed_intervention(db_session, rec_id, teacher_a, student_id, status="pending_review")

        client = _client_for(teacher_b, pg_dsn)
        resp = client.post(f"/api/v1/interventions/{rec_id}/approve")

        assert resp.status_code == 404, resp.text
        assert resp.json()["error"]["code"] == "NOT_FOUND"

    @pytest.mark.asyncio
    async def test_cross_teacher_dismiss_returns_404(
        self, db_session: AsyncSession, pg_dsn: str
    ) -> None:
        teacher_a = _uuid()
        teacher_b = _uuid()
        student_id = _uuid()
        rec_id = _uuid()

        await _seed_teacher(db_session, teacher_a)
        await _seed_teacher(db_session, teacher_b)
        await _seed_student(db_session, student_id, teacher_a)
        await _seed_intervention(db_session, rec_id, teacher_a, student_id, status="pending_review")

        client = _client_for(teacher_b, pg_dsn)
        resp = client.delete(f"/api/v1/interventions/{rec_id}")

        assert resp.status_code == 404, resp.text
        assert resp.json()["error"]["code"] == "NOT_FOUND"

    @pytest.mark.asyncio
    async def test_dismiss_approved_returns_409(
        self, db_session: AsyncSession, pg_dsn: str
    ) -> None:
        teacher_id = _uuid()
        student_id = _uuid()
        rec_id = _uuid()

        await _seed_teacher(db_session, teacher_id)
        await _seed_student(db_session, student_id, teacher_id)
        await _seed_intervention(db_session, rec_id, teacher_id, student_id, status="approved")

        client = _client_for(teacher_id, pg_dsn)
        resp = client.delete(f"/api/v1/interventions/{rec_id}")

        assert resp.status_code == 409, resp.text
        assert resp.json()["error"]["code"] == "CONFLICT"
