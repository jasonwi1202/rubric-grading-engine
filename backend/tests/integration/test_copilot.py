"""Integration tests for POST /api/v1/copilot/query (M7-03).

Tests exercise the full FastAPI stack with a real Postgres testcontainer
schema. LLM calls are mocked at the service boundary.

Covered:
- Happy path with class-scoped context and resolved student display names.
- 404 when class_id does not exist.
- 403 when class_id belongs to a different teacher.

No student PII in fixtures.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.dependencies import get_current_teacher, get_db
from app.llm.parsers import CopilotRankedItem, ParsedCopilotResponse
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


async def _seed_class(db: AsyncSession, class_id: uuid.UUID, teacher_id: uuid.UUID) -> None:
    await db.execute(
        text(
            "INSERT INTO classes "
            "(id, teacher_id, name, subject, grade_level, academic_year, is_archived) "
            "VALUES (:id, :tid, :name, :subj, :grade, :year, false) ON CONFLICT DO NOTHING"
        ),
        {
            "id": str(class_id),
            "tid": str(teacher_id),
            "name": "Class A",
            "subj": "English",
            "grade": "8",
            "year": "2025-2026",
        },
    )
    await db.commit()


async def _seed_student(db: AsyncSession, student_id: uuid.UUID, teacher_id: uuid.UUID) -> None:
    await db.execute(
        text(
            "INSERT INTO students (id, teacher_id, full_name) "
            "VALUES (:id, :tid, :name) ON CONFLICT DO NOTHING"
        ),
        {"id": str(student_id), "tid": str(teacher_id), "name": "Student One"},
    )
    await db.commit()


async def _seed_enrollment(db: AsyncSession, class_id: uuid.UUID, student_id: uuid.UUID) -> None:
    await db.execute(
        text(
            "INSERT INTO class_enrollments (id, class_id, student_id) "
            "VALUES (:id, :cid, :sid) ON CONFLICT DO NOTHING"
        ),
        {"id": str(_uuid()), "cid": str(class_id), "sid": str(student_id)},
    )
    await db.commit()


async def _seed_profile(db: AsyncSession, teacher_id: uuid.UUID, student_id: uuid.UUID) -> None:
    await db.execute(
        text(
            "INSERT INTO student_skill_profiles "
            "(id, teacher_id, student_id, skill_scores, assignment_count) "
            "VALUES (:id, :tid, :sid, CAST(:scores AS jsonb), :cnt) ON CONFLICT DO NOTHING"
        ),
        {
            "id": str(_uuid()),
            "tid": str(teacher_id),
            "sid": str(student_id),
            "scores": json.dumps(
                {"thesis": {"avg_score": 0.48, "trend": "stable", "data_points": 4}}
            ),
            "cnt": 4,
        },
    )
    await db.commit()


async def _seed_worklist(db: AsyncSession, teacher_id: uuid.UUID, student_id: uuid.UUID) -> None:
    await db.execute(
        text(
            "INSERT INTO teacher_worklist_items "
            "(id, teacher_id, student_id, trigger_type, skill_key, urgency, suggested_action, details, status) "
            "VALUES (:id, :tid, :sid, :tt, :skill, :urg, :action, CAST(:details AS jsonb), :status)"
        ),
        {
            "id": str(_uuid()),
            "tid": str(teacher_id),
            "sid": str(student_id),
            "tt": "persistent_gap",
            "skill": "thesis",
            "urg": 3,
            "action": "Provide thesis mini-lesson.",
            "details": json.dumps({"avg_score": 0.48, "trend": "stable", "assignment_count": 4}),
            "status": "active",
        },
    )
    await db.commit()


@pytest.mark.integration
class TestCopilotQueryIntegration:
    @pytest.mark.asyncio
    async def test_happy_path_returns_data_with_resolved_student_name(
        self, db_session: AsyncSession, pg_dsn: str
    ) -> None:
        teacher_id = _uuid()
        class_id = _uuid()
        student_id = _uuid()

        await _seed_teacher(db_session, teacher_id)
        await _seed_class(db_session, class_id, teacher_id)
        await _seed_student(db_session, student_id, teacher_id)
        await _seed_enrollment(db_session, class_id, student_id)
        await _seed_profile(db_session, teacher_id, student_id)
        await _seed_worklist(db_session, teacher_id, student_id)

        client = _client_for(teacher_id, pg_dsn)

        parsed = ParsedCopilotResponse(
            query_interpretation="Identify students needing thesis support.",
            has_sufficient_data=True,
            uncertainty_note=None,
            response_type="ranked_list",
            ranked_items=[
                CopilotRankedItem(
                    student_id=str(student_id),
                    skill_dimension="thesis",
                    label="Below threshold on thesis",
                    value=0.48,
                    explanation="avg_score is 0.48 with stable trend.",
                )
            ],
            summary="One student is below threshold on thesis.",
            suggested_next_steps=["Run a thesis mini-lesson."],
        )

        with patch("app.services.copilot.call_copilot", new=AsyncMock(return_value=parsed)):
            resp = client.post(
                "/api/v1/copilot/query",
                json={"query": "Who needs thesis help?", "class_id": str(class_id)},
            )

        assert resp.status_code == 200, resp.text
        body = resp.json()["data"]
        assert body["response_type"] == "ranked_list"
        assert body["has_sufficient_data"] is True
        assert body["ranked_items"][0]["student_id"] == str(student_id)
        assert body["ranked_items"][0]["student_display_name"] == "Student One"

    @pytest.mark.asyncio
    async def test_class_not_found_returns_404(self, db_session: AsyncSession, pg_dsn: str) -> None:
        teacher_id = _uuid()
        await _seed_teacher(db_session, teacher_id)

        client = _client_for(teacher_id, pg_dsn)
        resp = client.post(
            "/api/v1/copilot/query",
            json={"query": "Who needs help?", "class_id": str(_uuid())},
        )

        assert resp.status_code == 404, resp.text
        assert resp.json()["error"]["code"] == "NOT_FOUND"

    @pytest.mark.asyncio
    async def test_cross_teacher_class_returns_403(
        self, db_session: AsyncSession, pg_dsn: str
    ) -> None:
        teacher_a = _uuid()
        teacher_b = _uuid()
        class_id = _uuid()

        await _seed_teacher(db_session, teacher_a)
        await _seed_teacher(db_session, teacher_b)
        await _seed_class(db_session, class_id, teacher_a)

        client = _client_for(teacher_b, pg_dsn)
        resp = client.post(
            "/api/v1/copilot/query",
            json={"query": "Who needs help?", "class_id": str(class_id)},
        )

        assert resp.status_code == 403, resp.text
        assert resp.json()["error"]["code"] == "FORBIDDEN"
