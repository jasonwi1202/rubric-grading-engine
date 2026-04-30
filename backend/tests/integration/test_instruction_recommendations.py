"""Integration tests for instruction recommendation endpoints (M6-07).

Tests exercise the full stack: real PostgreSQL (via testcontainers),
Alembic-migrated schema, real ORM writes, mocked LLM.  Auth is injected via
FastAPI dependency override (same pattern as unit tests).

All three endpoints are covered:
  POST /api/v1/students/{studentId}/recommendations
  GET  /api/v1/students/{studentId}/recommendations
  POST /api/v1/classes/{classId}/groups/{groupId}/recommendations

Each endpoint has at least one happy-path test and one cross-teacher 403 test.

No student PII in fixtures.  The tests skip automatically if Docker is not
available (managed by the ``pg_dsn`` fixture in ``conftest.py``).
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.dependencies import get_current_teacher, get_db
from app.llm.parsers import ParsedInstructionResponse, ParsedRecommendation
from app.main import create_app
from app.models.user import User

# ---------------------------------------------------------------------------
# Helpers / factories — no PII in any literal value
# ---------------------------------------------------------------------------


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


def _make_parsed_response() -> ParsedInstructionResponse:
    """Return a minimal but structurally valid LLM parse result."""
    return ParsedInstructionResponse(
        recommendations=[
            ParsedRecommendation(
                skill_dimension="evidence",
                title="Evidence Workshop",
                description="Practice integrating evidence into body paragraphs.",
                estimated_minutes=20,
                strategy_type="guided_practice",
            )
        ]
    )


def _make_teacher_orm(teacher_id: uuid.UUID) -> MagicMock:
    """Build a mock User ORM object (enough for the dependency override)."""
    teacher = MagicMock(spec=User)
    teacher.id = teacher_id
    teacher.email = "teacher@school.edu"
    teacher.email_verified = True
    teacher.onboarding_complete = True
    return teacher


def _client_for(teacher_id: uuid.UUID, pg_dsn: str) -> TestClient:
    """Return a TestClient with auth and DB overridden for the given teacher.

    The DB override creates a *fresh* engine and AsyncSession per request from
    the DSN string.  Using the session-scoped AsyncEngine directly would bind
    asyncpg connections to the pytest-asyncio event loop, which differs from
    the anyio loop that TestClient runs under, causing a 'Future attached to a
    different loop' RuntimeError.
    """
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
# DB seeding helpers
# ---------------------------------------------------------------------------


async def _seed_teacher(db: AsyncSession, teacher_id: uuid.UUID) -> None:
    """Insert a minimal teacher (User) row, bypassing RLS as superuser."""
    await db.execute(
        text(
            "INSERT INTO users (id, email, hashed_password, first_name, last_name, "
            "school_name, email_verified, onboarding_complete) "
            "VALUES (:id, :email, :pwd, :fn, :ln, :school, true, true) "
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


async def _seed_student(
    db: AsyncSession,
    student_id: uuid.UUID,
    teacher_id: uuid.UUID,
) -> None:
    await db.execute(
        text(
            "INSERT INTO students (id, teacher_id, full_name) "
            "VALUES (:id, :tid, :name) ON CONFLICT DO NOTHING"
        ),
        {"id": str(student_id), "tid": str(teacher_id), "name": "Anonymous Student"},
    )
    await db.commit()


async def _seed_skill_profile(
    db: AsyncSession,
    student_id: uuid.UUID,
    teacher_id: uuid.UUID,
    skill_scores: dict[str, Any] | None = None,
) -> None:
    if skill_scores is None:
        skill_scores = {"evidence": {"avg_score": 0.4, "trend": "stable", "data_points": 3}}

    await db.execute(
        text(
            "INSERT INTO student_skill_profiles "
            "(id, teacher_id, student_id, skill_scores, assignment_count) "
            "VALUES (:id, :tid, :sid, CAST(:scores AS jsonb), 3) ON CONFLICT DO NOTHING"
        ),
        {
            "id": str(_uuid()),
            "tid": str(teacher_id),
            "sid": str(student_id),
            "scores": json.dumps(skill_scores),
        },
    )
    await db.commit()


async def _seed_class(
    db: AsyncSession,
    class_id: uuid.UUID,
    teacher_id: uuid.UUID,
) -> None:
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


async def _seed_group(
    db: AsyncSession,
    group_id: uuid.UUID,
    class_id: uuid.UUID,
    teacher_id: uuid.UUID,
    skill_key: str = "evidence",
    student_count: int = 3,
) -> None:
    await db.execute(
        text(
            "INSERT INTO student_groups "
            "(id, teacher_id, class_id, skill_key, label, student_ids, student_count, stability) "
            "VALUES (:id, :tid, :cid, :sk, :label, CAST(:sids AS jsonb), :cnt, 'persistent') "
            "ON CONFLICT DO NOTHING"
        ),
        {
            "id": str(group_id),
            "tid": str(teacher_id),
            "cid": str(class_id),
            "sk": skill_key,
            "label": f"Needs work on {skill_key}",
            "sids": json.dumps([]),
            "cnt": student_count,
        },
    )
    await db.commit()


# ---------------------------------------------------------------------------
# POST /api/v1/students/{studentId}/recommendations — integration tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestGenerateStudentRecommendationsIntegration:
    @pytest.mark.asyncio
    async def test_happy_path_persists_recommendation_to_db(
        self, db_session: AsyncSession, pg_dsn: str
    ) -> None:
        """POSTing to the generate endpoint writes a row to instruction_recommendations."""
        teacher_id = _uuid()
        student_id = _uuid()

        await _seed_teacher(db_session, teacher_id)
        await _seed_student(db_session, student_id, teacher_id)
        await _seed_skill_profile(db_session, student_id, teacher_id)

        client = _client_for(teacher_id, pg_dsn)

        with patch(
            "app.services.instruction_recommendation.call_instruction",
            new_callable=AsyncMock,
            return_value=_make_parsed_response(),
        ):
            resp = client.post(
                f"/api/v1/students/{student_id}/recommendations",
                json={"grade_level": "Grade 8", "duration_minutes": 20},
            )

        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert "data" in body
        data = body["data"]
        assert data["teacher_id"] == str(teacher_id)
        assert data["student_id"] == str(student_id)
        assert data["group_id"] is None
        assert data["status"] == "pending_review"
        assert len(data["recommendations"]) == 1
        assert data["recommendations"][0]["skill_dimension"] == "evidence"

        # Verify the row was actually written to the DB
        result = await db_session.execute(
            text(
                "SELECT id, teacher_id, student_id, status "
                "FROM instruction_recommendations "
                "WHERE teacher_id = :tid AND student_id = :sid"
            ),
            {"tid": str(teacher_id), "sid": str(student_id)},
        )
        rows = result.fetchall()
        assert len(rows) == 1
        assert rows[0].status == "pending_review"

    @pytest.mark.asyncio
    async def test_cross_teacher_student_returns_403(
        self, db_session: AsyncSession, pg_dsn: str
    ) -> None:
        """Teacher B cannot generate recommendations for Teacher A's student."""
        teacher_a_id = _uuid()
        teacher_b_id = _uuid()
        student_id = _uuid()

        await _seed_teacher(db_session, teacher_a_id)
        await _seed_teacher(db_session, teacher_b_id)
        await _seed_student(db_session, student_id, teacher_a_id)

        # Teacher B attempts to POST to Teacher A's student
        client = _client_for(teacher_b_id, pg_dsn)
        with patch(
            "app.services.instruction_recommendation.call_instruction",
            new_callable=AsyncMock,
            return_value=_make_parsed_response(),
        ):
            resp = client.post(
                f"/api/v1/students/{student_id}/recommendations",
                json={"grade_level": "Grade 8", "duration_minutes": 20},
            )

        assert resp.status_code == 403, resp.text


# ---------------------------------------------------------------------------
# GET /api/v1/students/{studentId}/recommendations — integration tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestListStudentRecommendationsIntegration:
    @pytest.mark.asyncio
    async def test_returns_persisted_recommendations(
        self, db_session: AsyncSession, pg_dsn: str
    ) -> None:
        """GET returns rows that were previously written for the student."""
        teacher_id = _uuid()
        student_id = _uuid()
        rec_id = _uuid()

        await _seed_teacher(db_session, teacher_id)
        await _seed_student(db_session, student_id, teacher_id)

        # Seed a recommendation row directly
        await db_session.execute(
            text(
                "INSERT INTO instruction_recommendations "
                "(id, teacher_id, student_id, group_id, grade_level, prompt_version, "
                "recommendations, evidence_summary, status) "
                "VALUES (:id, :tid, :sid, NULL, :gl, :pv, CAST(:recs AS jsonb), :ev, :st)"
            ),
            {
                "id": str(rec_id),
                "tid": str(teacher_id),
                "sid": str(student_id),
                "gl": "Grade 8",
                "pv": "instruction-v1",
                "recs": json.dumps(
                    [
                        {
                            "skill_dimension": "evidence",
                            "title": "Evidence Workshop",
                            "description": "Practice evidence integration.",
                            "estimated_minutes": 20,
                            "strategy_type": "guided_practice",
                        }
                    ]
                ),
                "ev": "Skill gap in evidence.",
                "st": "pending_review",
            },
        )
        await db_session.commit()

        client = _client_for(teacher_id, pg_dsn)
        resp = client.get(f"/api/v1/students/{student_id}/recommendations")

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "data" in body
        assert isinstance(body["data"], list)
        matching = [r for r in body["data"] if r["id"] == str(rec_id)]
        assert len(matching) == 1
        assert matching[0]["status"] == "pending_review"

    @pytest.mark.asyncio
    async def test_cross_teacher_student_returns_403(
        self, db_session: AsyncSession, pg_dsn: str
    ) -> None:
        """Teacher B cannot list recommendations for Teacher A's student."""
        teacher_a_id = _uuid()
        teacher_b_id = _uuid()
        student_id = _uuid()

        await _seed_teacher(db_session, teacher_a_id)
        await _seed_teacher(db_session, teacher_b_id)
        await _seed_student(db_session, student_id, teacher_a_id)

        client = _client_for(teacher_b_id, pg_dsn)
        resp = client.get(f"/api/v1/students/{student_id}/recommendations")

        assert resp.status_code == 403, resp.text


# ---------------------------------------------------------------------------
# POST /api/v1/classes/{classId}/groups/{groupId}/recommendations — integration
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestGenerateGroupRecommendationsIntegration:
    @pytest.mark.asyncio
    async def test_happy_path_persists_recommendation_to_db(
        self, db_session: AsyncSession, pg_dsn: str
    ) -> None:
        """POSTing to the group endpoint writes a row to instruction_recommendations."""
        teacher_id = _uuid()
        class_id = _uuid()
        group_id = _uuid()

        await _seed_teacher(db_session, teacher_id)
        await _seed_class(db_session, class_id, teacher_id)
        await _seed_group(db_session, group_id, class_id, teacher_id)

        client = _client_for(teacher_id, pg_dsn)

        with patch(
            "app.services.instruction_recommendation.call_instruction",
            new_callable=AsyncMock,
            return_value=_make_parsed_response(),
        ):
            resp = client.post(
                f"/api/v1/classes/{class_id}/groups/{group_id}/recommendations",
                json={"grade_level": "Grade 8", "duration_minutes": 20},
            )

        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert "data" in body
        data = body["data"]
        assert data["teacher_id"] == str(teacher_id)
        assert data["group_id"] == str(group_id)
        assert data["student_id"] is None
        assert data["status"] == "pending_review"

        # Verify the row was actually written to the DB
        result = await db_session.execute(
            text(
                "SELECT id, teacher_id, group_id, status "
                "FROM instruction_recommendations "
                "WHERE teacher_id = :tid AND group_id = :gid"
            ),
            {"tid": str(teacher_id), "gid": str(group_id)},
        )
        rows = result.fetchall()
        assert len(rows) == 1
        assert rows[0].status == "pending_review"

    @pytest.mark.asyncio
    async def test_cross_teacher_group_returns_403(
        self, db_session: AsyncSession, pg_dsn: str
    ) -> None:
        """Teacher B cannot generate recommendations for Teacher A's group."""
        teacher_a_id = _uuid()
        teacher_b_id = _uuid()
        class_id = _uuid()
        group_id = _uuid()

        await _seed_teacher(db_session, teacher_a_id)
        await _seed_teacher(db_session, teacher_b_id)
        await _seed_class(db_session, class_id, teacher_a_id)
        await _seed_group(db_session, group_id, class_id, teacher_a_id)

        client = _client_for(teacher_b_id, pg_dsn)
        with patch(
            "app.services.instruction_recommendation.call_instruction",
            new_callable=AsyncMock,
            return_value=_make_parsed_response(),
        ):
            resp = client.post(
                f"/api/v1/classes/{class_id}/groups/{group_id}/recommendations",
                json={"grade_level": "Grade 8", "duration_minutes": 20},
            )

        assert resp.status_code == 403, resp.text


# ---------------------------------------------------------------------------
# POST /api/v1/recommendations/{recommendationId}/assign — integration tests
# ---------------------------------------------------------------------------


async def _seed_recommendation(
    db: AsyncSession,
    rec_id: uuid.UUID,
    teacher_id: uuid.UUID,
    *,
    student_id: uuid.UUID | None = None,
    group_id: uuid.UUID | None = None,
    status: str = "pending_review",
) -> None:
    """Seed a minimal instruction_recommendations row for testing."""
    await db.execute(
        text(
            "INSERT INTO instruction_recommendations "
            "(id, teacher_id, student_id, group_id, grade_level, prompt_version, "
            "recommendations, evidence_summary, status) "
            "VALUES (:id, :tid, :sid, :gid, :gl, :pv, CAST(:recs AS jsonb), :ev, :st)"
        ),
        {
            "id": str(rec_id),
            "tid": str(teacher_id),
            "sid": str(student_id) if student_id else None,
            "gid": str(group_id) if group_id else None,
            "gl": "Grade 8",
            "pv": "instruction-v1",
            "recs": json.dumps(
                [
                    {
                        "skill_dimension": "evidence",
                        "title": "Evidence Workshop",
                        "description": "Practice evidence integration.",
                        "estimated_minutes": 20,
                        "strategy_type": "guided_practice",
                    }
                ]
            ),
            "ev": "Skill gap in evidence.",
            "st": status,
        },
    )
    await db.commit()


@pytest.mark.integration
class TestAssignRecommendationIntegration:
    @pytest.mark.asyncio
    async def test_happy_path_transitions_status_to_accepted(
        self, db_session: AsyncSession, pg_dsn: str
    ) -> None:
        """POST /assign transitions status from pending_review to accepted."""
        teacher_id = _uuid()
        student_id = _uuid()
        rec_id = _uuid()

        await _seed_teacher(db_session, teacher_id)
        await _seed_student(db_session, student_id, teacher_id)
        await _seed_recommendation(
            db_session, rec_id, teacher_id, student_id=student_id
        )

        client = _client_for(teacher_id, pg_dsn)
        resp = client.post(f"/api/v1/recommendations/{rec_id}/assign")

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "data" in body
        data = body["data"]
        assert data["id"] == str(rec_id)
        assert data["status"] == "accepted"

        # Confirm DB reflects the new status.
        result = await db_session.execute(
            text(
                "SELECT status FROM instruction_recommendations WHERE id = :id"
            ),
            {"id": str(rec_id)},
        )
        row = result.fetchone()
        assert row is not None
        assert row.status == "accepted"

        # Confirm audit log entry was written.
        result = await db_session.execute(
            text(
                "SELECT action, before_value, after_value "
                "FROM audit_logs "
                "WHERE entity_type = 'instruction_recommendation' "
                "  AND entity_id = :eid"
            ),
            {"eid": str(rec_id)},
        )
        audit_rows = result.fetchall()
        assert len(audit_rows) == 1
        assert audit_rows[0].action == "recommendation_assigned"

    @pytest.mark.asyncio
    async def test_idempotent_when_already_accepted(
        self, db_session: AsyncSession, pg_dsn: str
    ) -> None:
        """POST /assign is idempotent: calling twice on an accepted rec returns 200."""
        teacher_id = _uuid()
        student_id = _uuid()
        rec_id = _uuid()

        await _seed_teacher(db_session, teacher_id)
        await _seed_student(db_session, student_id, teacher_id)
        await _seed_recommendation(
            db_session, rec_id, teacher_id, student_id=student_id, status="accepted"
        )

        client = _client_for(teacher_id, pg_dsn)
        resp = client.post(f"/api/v1/recommendations/{rec_id}/assign")

        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["status"] == "accepted"

    @pytest.mark.asyncio
    async def test_dismissed_recommendation_returns_409(
        self, db_session: AsyncSession, pg_dsn: str
    ) -> None:
        """POST /assign on a dismissed recommendation returns 409 Conflict."""
        teacher_id = _uuid()
        student_id = _uuid()
        rec_id = _uuid()

        await _seed_teacher(db_session, teacher_id)
        await _seed_student(db_session, student_id, teacher_id)
        await _seed_recommendation(
            db_session, rec_id, teacher_id, student_id=student_id, status="dismissed"
        )

        client = _client_for(teacher_id, pg_dsn)
        resp = client.post(f"/api/v1/recommendations/{rec_id}/assign")

        assert resp.status_code == 409, resp.text

    @pytest.mark.asyncio
    async def test_cross_teacher_returns_403(
        self, db_session: AsyncSession, pg_dsn: str
    ) -> None:
        """Teacher B cannot assign Teacher A's recommendation."""
        teacher_a_id = _uuid()
        teacher_b_id = _uuid()
        student_id = _uuid()
        rec_id = _uuid()

        await _seed_teacher(db_session, teacher_a_id)
        await _seed_teacher(db_session, teacher_b_id)
        await _seed_student(db_session, student_id, teacher_a_id)
        await _seed_recommendation(
            db_session, rec_id, teacher_a_id, student_id=student_id
        )

        client = _client_for(teacher_b_id, pg_dsn)
        resp = client.post(f"/api/v1/recommendations/{rec_id}/assign")

        assert resp.status_code == 403, resp.text

    @pytest.mark.asyncio
    async def test_nonexistent_recommendation_returns_404(
        self, db_session: AsyncSession, pg_dsn: str
    ) -> None:
        """POST /assign on a nonexistent recommendation ID returns 404."""
        teacher_id = _uuid()
        await _seed_teacher(db_session, teacher_id)

        client = _client_for(teacher_id, pg_dsn)
        resp = client.post(f"/api/v1/recommendations/{_uuid()}/assign")

        assert resp.status_code == 404, resp.text
