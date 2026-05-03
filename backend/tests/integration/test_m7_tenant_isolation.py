"""Integration tests for cross-teacher tenant isolation — M7 tables.

Verifies that teacher B cannot read resources owned by teacher A for the M7
tables: ``intervention_recommendations``.

The copilot endpoint's cross-teacher isolation (403 when class_id belongs to
another teacher) is already covered in ``test_copilot.py``.  This module adds
the complementary **list-isolation** assertion: ``GET /interventions`` must
never expose another teacher's recommendations, even when both teachers have
pending items.

Service-layer ``WHERE teacher_id = ?`` scoping is what's being exercised here.
The testcontainers superuser bypasses PostgreSQL FORCE RLS, so RLS policy
correctness is validated in ``test_rls_policy_enforcement.py`` instead.

Tests skip automatically when Docker is unavailable.
No student PII in any fixture.
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


# ---------------------------------------------------------------------------
# Intervention list isolation
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestInterventionListTenantIsolation:
    """Teacher B's GET /interventions must not expose Teacher A's items."""

    @pytest.mark.asyncio
    async def test_list_does_not_expose_another_teachers_interventions(
        self, db_session: AsyncSession, pg_dsn: str
    ) -> None:
        """GET /interventions returns only the authenticated teacher's items.

        Even when both teachers have pending interventions, Teacher B must
        only see their own rows.
        """
        teacher_a = _uuid()
        teacher_b = _uuid()
        student_a = _uuid()
        student_b = _uuid()
        rec_a = _uuid()
        rec_b = _uuid()

        await _seed_teacher(db_session, teacher_a)
        await _seed_teacher(db_session, teacher_b)
        await _seed_student(db_session, student_a, teacher_a)
        await _seed_student(db_session, student_b, teacher_b)
        await _seed_intervention(db_session, rec_a, teacher_a, student_a)
        await _seed_intervention(db_session, rec_b, teacher_b, student_b)

        client = _client_for(teacher_b, pg_dsn)
        resp = client.get("/api/v1/interventions")

        assert resp.status_code == 200, resp.text
        body = resp.json()["data"]
        returned_ids = [item["id"] for item in body["items"]]
        assert str(rec_b) in returned_ids, "Teacher B's own item must be returned"
        assert str(rec_a) not in returned_ids, (
            "Teacher A's intervention must not appear in Teacher B's list"
        )

    @pytest.mark.asyncio
    async def test_list_with_status_all_does_not_expose_another_teachers_interventions(
        self, db_session: AsyncSession, pg_dsn: str
    ) -> None:
        """GET /interventions?status=all also respects tenant scoping.

        The ``status=all`` filter broadens which statuses are returned but must
        still restrict results to the authenticated teacher's rows.
        """
        teacher_a = _uuid()
        teacher_b = _uuid()
        student_a = _uuid()
        student_b = _uuid()
        rec_a = _uuid()
        rec_b = _uuid()

        await _seed_teacher(db_session, teacher_a)
        await _seed_teacher(db_session, teacher_b)
        await _seed_student(db_session, student_a, teacher_a)
        await _seed_student(db_session, student_b, teacher_b)
        # Seed an approved item for each teacher so status=all would return both
        # if isolation were absent.
        await _seed_intervention(db_session, rec_a, teacher_a, student_a, status="approved")
        await _seed_intervention(db_session, rec_b, teacher_b, student_b, status="approved")

        client = _client_for(teacher_b, pg_dsn)
        resp = client.get("/api/v1/interventions?status=all")

        assert resp.status_code == 200, resp.text
        body = resp.json()["data"]
        returned_ids = [item["id"] for item in body["items"]]
        assert str(rec_b) in returned_ids
        assert str(rec_a) not in returned_ids, (
            "Teacher A's approved intervention must not appear in Teacher B's status=all list"
        )

    @pytest.mark.asyncio
    async def test_empty_list_when_teacher_has_no_interventions(
        self, db_session: AsyncSession, pg_dsn: str
    ) -> None:
        """GET /interventions returns an empty list (not 404) when no items exist."""
        teacher_id = _uuid()
        await _seed_teacher(db_session, teacher_id)

        client = _client_for(teacher_id, pg_dsn)
        resp = client.get("/api/v1/interventions")

        assert resp.status_code == 200, resp.text
        body = resp.json()["data"]
        assert body["items"] == []
        assert body["total_count"] == 0
