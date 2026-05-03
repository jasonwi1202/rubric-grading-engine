"""Integration tests for cross-teacher tenant isolation — selected M6 tables.

Verifies that teacher B cannot read or modify resources owned by teacher A for
the M6 tables covered in this module: student_groups and
teacher_worklist_items. Isolation coverage for instruction_recommendations
lives in separate integration tests.

These tests validate **service-layer ``teacher_id`` scoping** (every query
carries a ``teacher_id`` predicate that limits results to the authenticated
teacher's rows).  They do *not* exercise PostgreSQL FORCE ROW LEVEL SECURITY
directly: the testcontainers DB user is a superuser and therefore BYPASSRLS,
so RLS policies are not evaluated.  The isolation guarantee under test is the
ORM-level ``WHERE teacher_id = ?`` filter applied by the service layer.

Tests exercise the full stack: real PostgreSQL (via testcontainers), Alembic-
migrated schema, real ORM writes.  Auth is injected via FastAPI dependency
override.  No student PII in any fixture or assertion.

Tests skip automatically when Docker is unavailable (managed by the ``pg_dsn``
fixture in ``conftest.py``).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from datetime import UTC
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.dependencies import get_current_teacher, get_db
from app.main import create_app
from app.models.user import User

# ---------------------------------------------------------------------------
# Helpers / factories — no PII in any literal value
# ---------------------------------------------------------------------------


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


def _make_teacher_orm(teacher_id: uuid.UUID) -> MagicMock:
    """Build a minimal User-like object sufficient for the auth dependency override."""
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

    Note: the testcontainers DB user is a superuser (BYPASSRLS), so
    ``SET app.current_teacher_id`` has no effect on RLS enforcement.  Tenant
    isolation here is enforced by the service-layer ``WHERE teacher_id = ?``
    predicate, not by PostgreSQL FORCE RLS.
    """
    teacher_orm = _make_teacher_orm(teacher_id)
    app = create_app()
    app.dependency_overrides[get_current_teacher] = lambda: teacher_orm

    async def _get_test_db() -> AsyncGenerator[AsyncSession, None]:
        engine = create_async_engine(pg_dsn, echo=False)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            await session.execute(
                text("SELECT set_config('app.current_teacher_id', :teacher_id, true)"),
                {"teacher_id": str(teacher_id)},
            )
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


async def _seed_enrollment(
    db: AsyncSession,
    student_id: uuid.UUID,
    class_id: uuid.UUID,
) -> None:
    """Enroll a student in a class (active enrollment, no removed_at)."""
    import uuid as _uuid

    await db.execute(
        text(
            "INSERT INTO class_enrollments (id, student_id, class_id) "
            "VALUES (:id, :sid, :cid) ON CONFLICT DO NOTHING"
        ),
        {"id": str(_uuid.uuid4()), "sid": str(student_id), "cid": str(class_id)},
    )
    await db.commit()


async def _seed_group(
    db: AsyncSession,
    group_id: uuid.UUID,
    class_id: uuid.UUID,
    teacher_id: uuid.UUID,
    skill_key: str = "evidence",
    student_ids: list[str] | None = None,
) -> None:
    import json as _json

    sids = _json.dumps(student_ids or [])
    count = len(student_ids) if student_ids else 0
    await db.execute(
        text(
            "INSERT INTO student_groups "
            "(id, teacher_id, class_id, skill_key, label, student_ids, student_count, stability) "
            "VALUES (:id, :tid, :cid, :sk, :label, CAST(:sids AS jsonb), :count, 'persistent') "
            "ON CONFLICT DO NOTHING"
        ),
        {
            "id": str(group_id),
            "tid": str(teacher_id),
            "cid": str(class_id),
            "sk": skill_key,
            "label": skill_key.title(),
            "sids": sids,
            "count": count,
        },
    )
    await db.commit()


async def _seed_worklist_item(
    db: AsyncSession,
    item_id: uuid.UUID,
    teacher_id: uuid.UUID,
    student_id: uuid.UUID,
    status: str = "active",
) -> None:
    await db.execute(
        text(
            "INSERT INTO teacher_worklist_items "
            "(id, teacher_id, student_id, trigger_type, urgency, suggested_action, "
            "details, status, generated_at, created_at) "
            "VALUES (:id, :tid, :sid, :tt, :urg, :action, "
            "CAST(:details AS jsonb), :status, now(), now()) "
            "ON CONFLICT DO NOTHING"
        ),
        {
            "id": str(item_id),
            "tid": str(teacher_id),
            "sid": str(student_id),
            "tt": "persistent_gap",
            "urg": 3,
            "action": "Schedule a targeted session",
            "details": "{}",
            "status": status,
        },
    )
    await db.commit()


# ---------------------------------------------------------------------------
# Student Groups — cross-teacher isolation tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestStudentGroupsIntegrationTenantIsolation:
    """Integration tests verifying Teacher B cannot access Teacher A's groups."""

    @pytest.mark.asyncio
    async def test_get_groups_returns_403_for_another_teachers_class(
        self, db_session: AsyncSession, pg_dsn: str
    ) -> None:
        """GET /classes/{classId}/groups returns 403 when the class belongs to another teacher."""
        teacher_a_id = _uuid()
        teacher_b_id = _uuid()
        class_id = _uuid()

        await _seed_teacher(db_session, teacher_a_id)
        await _seed_teacher(db_session, teacher_b_id)
        await _seed_class(db_session, class_id, teacher_a_id)

        # Teacher B attempts to read Teacher A's groups
        client = _client_for(teacher_b_id, pg_dsn)
        resp = client.get(f"/api/v1/classes/{class_id}/groups")

        assert resp.status_code == 403, resp.text

    @pytest.mark.asyncio
    async def test_get_groups_returns_own_groups(
        self, db_session: AsyncSession, pg_dsn: str
    ) -> None:
        """GET /classes/{classId}/groups returns 200 with the teacher's own groups."""
        teacher_id = _uuid()
        class_id = _uuid()
        group_id = _uuid()

        await _seed_teacher(db_session, teacher_id)
        await _seed_class(db_session, class_id, teacher_id)
        await _seed_group(db_session, group_id, class_id, teacher_id)

        client = _client_for(teacher_id, pg_dsn)
        resp = client.get(f"/api/v1/classes/{class_id}/groups")

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "data" in body
        groups = body["data"]["groups"]
        assert any(g["id"] == str(group_id) for g in groups)

    @pytest.mark.asyncio
    async def test_patch_group_returns_403_for_another_teachers_class(
        self, db_session: AsyncSession, pg_dsn: str
    ) -> None:
        """PATCH /classes/{classId}/groups/{groupId} returns 403 when class belongs to another teacher."""
        teacher_a_id = _uuid()
        teacher_b_id = _uuid()
        class_id = _uuid()
        group_id = _uuid()

        await _seed_teacher(db_session, teacher_a_id)
        await _seed_teacher(db_session, teacher_b_id)
        await _seed_class(db_session, class_id, teacher_a_id)
        await _seed_group(db_session, group_id, class_id, teacher_a_id)

        # Teacher B attempts to PATCH Teacher A's group
        client = _client_for(teacher_b_id, pg_dsn)
        resp = client.patch(
            f"/api/v1/classes/{class_id}/groups/{group_id}",
            json={"student_ids": []},
        )

        assert resp.status_code == 403, resp.text


# ---------------------------------------------------------------------------
# Worklist — cross-teacher isolation tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestWorklistIntegrationTenantIsolation:
    """Integration tests verifying Teacher B cannot access Teacher A's worklist items."""

    @pytest.mark.asyncio
    async def test_get_worklist_does_not_expose_another_teachers_items(
        self, db_session: AsyncSession, pg_dsn: str
    ) -> None:
        """GET /worklist returns only the authenticated teacher's items.

        Teacher B's worklist must not contain Teacher A's items even when both
        teachers have active worklist items in the database.
        """
        teacher_a_id = _uuid()
        teacher_b_id = _uuid()
        student_a_id = _uuid()
        student_b_id = _uuid()
        item_a_id = _uuid()
        item_b_id = _uuid()

        await _seed_teacher(db_session, teacher_a_id)
        await _seed_teacher(db_session, teacher_b_id)
        await _seed_student(db_session, student_a_id, teacher_a_id)
        await _seed_student(db_session, student_b_id, teacher_b_id)
        await _seed_worklist_item(db_session, item_a_id, teacher_a_id, student_a_id)
        await _seed_worklist_item(db_session, item_b_id, teacher_b_id, student_b_id)

        # Teacher B should only see their own items
        client = _client_for(teacher_b_id, pg_dsn)
        resp = client.get("/api/v1/worklist")

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "data" in body
        item_ids = [item["id"] for item in body["data"]["items"]]
        assert len(item_ids) == 1, f"Expected exactly 1 item for Teacher B, got {len(item_ids)}"
        assert str(item_b_id) in item_ids, "Teacher B's own item should be returned"
        assert str(item_a_id) not in item_ids, (
            "Teacher A's item must not appear in Teacher B's worklist"
        )

    @pytest.mark.asyncio
    async def test_complete_worklist_item_returns_404_for_another_teachers_item(
        self, db_session: AsyncSession, pg_dsn: str
    ) -> None:
        """POST /worklist/{itemId}/complete returns 404 when the item belongs to another teacher.

        The service-layer lookup is scoped by both ``item_id`` and the authenticated
        ``teacher_id``, so Teacher B cannot match Teacher A's row. A cross-tenant
        ``item_id`` and a nonexistent ``item_id`` are therefore indistinguishable
        and both return 404.
        """
        teacher_a_id = _uuid()
        teacher_b_id = _uuid()
        student_a_id = _uuid()
        item_a_id = _uuid()

        await _seed_teacher(db_session, teacher_a_id)
        await _seed_teacher(db_session, teacher_b_id)
        await _seed_student(db_session, student_a_id, teacher_a_id)
        await _seed_worklist_item(db_session, item_a_id, teacher_a_id, student_a_id)

        # Teacher B attempts to complete Teacher A's item
        client = _client_for(teacher_b_id, pg_dsn)
        resp = client.post(f"/api/v1/worklist/{item_a_id}/complete")

        assert resp.status_code == 404, resp.text

    @pytest.mark.asyncio
    async def test_snooze_worklist_item_returns_404_for_another_teachers_item(
        self, db_session: AsyncSession, pg_dsn: str
    ) -> None:
        """POST /worklist/{itemId}/snooze returns 404 for a cross-tenant item.

        The service-layer lookup is scoped by ``(item_id, teacher_id)``, so a
        cross-tenant ID is indistinguishable from a nonexistent ID — both return 404.
        """
        teacher_a_id = _uuid()
        teacher_b_id = _uuid()
        student_a_id = _uuid()
        item_a_id = _uuid()

        await _seed_teacher(db_session, teacher_a_id)
        await _seed_teacher(db_session, teacher_b_id)
        await _seed_student(db_session, student_a_id, teacher_a_id)
        await _seed_worklist_item(db_session, item_a_id, teacher_a_id, student_a_id)

        # Teacher B attempts to snooze Teacher A's item
        client = _client_for(teacher_b_id, pg_dsn)
        resp = client.post(f"/api/v1/worklist/{item_a_id}/snooze", json={})

        assert resp.status_code == 404, resp.text

    @pytest.mark.asyncio
    async def test_dismiss_worklist_item_returns_404_for_another_teachers_item(
        self, db_session: AsyncSession, pg_dsn: str
    ) -> None:
        """DELETE /worklist/{itemId} returns 404 for a cross-tenant item.

        The service-layer lookup is scoped by ``(item_id, teacher_id)``, so a
        cross-tenant ID is indistinguishable from a nonexistent ID — both return 404.
        """
        teacher_a_id = _uuid()
        teacher_b_id = _uuid()
        student_a_id = _uuid()
        item_a_id = _uuid()

        await _seed_teacher(db_session, teacher_a_id)
        await _seed_teacher(db_session, teacher_b_id)
        await _seed_student(db_session, student_a_id, teacher_a_id)
        await _seed_worklist_item(db_session, item_a_id, teacher_a_id, student_a_id)

        # Teacher B attempts to dismiss Teacher A's item
        client = _client_for(teacher_b_id, pg_dsn)
        resp = client.delete(f"/api/v1/worklist/{item_a_id}")

        assert resp.status_code == 404, resp.text

    @pytest.mark.asyncio
    async def test_complete_own_worklist_item_succeeds(
        self, db_session: AsyncSession, pg_dsn: str
    ) -> None:
        """POST /worklist/{itemId}/complete returns 200 for the owning teacher's item."""
        teacher_id = _uuid()
        student_id = _uuid()
        item_id = _uuid()

        await _seed_teacher(db_session, teacher_id)
        await _seed_student(db_session, student_id, teacher_id)
        await _seed_worklist_item(db_session, item_id, teacher_id, student_id)

        client = _client_for(teacher_id, pg_dsn)
        resp = client.post(f"/api/v1/worklist/{item_id}/complete")

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "data" in body
        assert body["data"]["id"] == str(item_id)
        assert body["data"]["status"] == "completed"

    @pytest.mark.asyncio
    async def test_snooze_own_worklist_item_succeeds(
        self, db_session: AsyncSession, pg_dsn: str
    ) -> None:
        """POST /worklist/{itemId}/snooze returns 200 and status='snoozed' for the owning teacher."""
        teacher_id = _uuid()
        student_id = _uuid()
        item_id = _uuid()

        await _seed_teacher(db_session, teacher_id)
        await _seed_student(db_session, student_id, teacher_id)
        await _seed_worklist_item(db_session, item_id, teacher_id, student_id)

        from datetime import datetime, timedelta

        snooze_until = (datetime.now(tz=UTC) + timedelta(days=7)).isoformat()

        client = _client_for(teacher_id, pg_dsn)
        resp = client.post(
            f"/api/v1/worklist/{item_id}/snooze", json={"snooze_until": snooze_until}
        )

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "data" in body
        assert body["data"]["id"] == str(item_id)
        assert body["data"]["status"] == "snoozed"

    @pytest.mark.asyncio
    async def test_dismiss_own_worklist_item_succeeds(
        self, db_session: AsyncSession, pg_dsn: str
    ) -> None:
        """DELETE /worklist/{itemId} returns 200 and removes the item for the owning teacher."""
        teacher_id = _uuid()
        student_id = _uuid()
        item_id = _uuid()

        await _seed_teacher(db_session, teacher_id)
        await _seed_student(db_session, student_id, teacher_id)
        await _seed_worklist_item(db_session, item_id, teacher_id, student_id)

        client = _client_for(teacher_id, pg_dsn)
        resp = client.delete(f"/api/v1/worklist/{item_id}")

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "data" in body
        assert body["data"]["id"] == str(item_id)
        assert body["data"]["status"] == "dismissed"


# ---------------------------------------------------------------------------
# Student Groups — happy-path mutation tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestStudentGroupsMutationIntegration:
    """Integration tests for the PATCH /classes/{classId}/groups/{groupId} happy path."""

    @pytest.mark.asyncio
    async def test_patch_group_updates_student_membership(
        self, db_session: AsyncSession, pg_dsn: str
    ) -> None:
        """PATCH /classes/{classId}/groups/{groupId} returns 200 and persists the updated student_ids."""
        teacher_id = _uuid()
        class_id = _uuid()
        group_id = _uuid()
        student1_id = _uuid()
        student2_id = _uuid()

        await _seed_teacher(db_session, teacher_id)
        await _seed_class(db_session, class_id, teacher_id)
        # Seed both students so the service can resolve their names.
        await _seed_student(db_session, student1_id, teacher_id)
        await _seed_student(db_session, student2_id, teacher_id)
        # Enroll both students in the class so the service includes them after filtering.
        await _seed_enrollment(db_session, student1_id, class_id)
        await _seed_enrollment(db_session, student2_id, class_id)
        # Group starts with both students.
        await _seed_group(
            db_session,
            group_id,
            class_id,
            teacher_id,
            student_ids=[str(student1_id), str(student2_id)],
        )

        # PATCH to remove student2 — only student1 remains.
        client = _client_for(teacher_id, pg_dsn)
        resp = client.patch(
            f"/api/v1/classes/{class_id}/groups/{group_id}",
            json={"student_ids": [str(student1_id)]},
        )

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "data" in body
        returned_ids = [s["id"] for s in body["data"]["students"]]
        assert str(student1_id) in returned_ids
        assert str(student2_id) not in returned_ids

    @pytest.mark.asyncio
    async def test_patch_group_with_empty_list_clears_members(
        self, db_session: AsyncSession, pg_dsn: str
    ) -> None:
        """PATCH with an empty student_ids list clears all group members."""
        teacher_id = _uuid()
        class_id = _uuid()
        group_id = _uuid()
        student_id = _uuid()

        await _seed_teacher(db_session, teacher_id)
        await _seed_class(db_session, class_id, teacher_id)
        await _seed_student(db_session, student_id, teacher_id)
        await _seed_enrollment(db_session, student_id, class_id)
        await _seed_group(
            db_session,
            group_id,
            class_id,
            teacher_id,
            student_ids=[str(student_id)],
        )

        client = _client_for(teacher_id, pg_dsn)
        resp = client.patch(
            f"/api/v1/classes/{class_id}/groups/{group_id}",
            json={"student_ids": []},
        )

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["data"]["students"] == []


# ---------------------------------------------------------------------------
# Class Insights — cross-teacher isolation tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestClassInsightsIntegrationTenantIsolation:
    """GET /classes/{classId}/insights must return 403 for another teacher's class."""

    @pytest.mark.asyncio
    async def test_get_insights_returns_403_for_another_teachers_class(
        self, db_session: AsyncSession, pg_dsn: str
    ) -> None:
        """Teacher B cannot read insights for Teacher A's class."""
        teacher_a_id = _uuid()
        teacher_b_id = _uuid()
        class_id = _uuid()

        await _seed_teacher(db_session, teacher_a_id)
        await _seed_teacher(db_session, teacher_b_id)
        await _seed_class(db_session, class_id, teacher_a_id)

        client = _client_for(teacher_b_id, pg_dsn)
        resp = client.get(f"/api/v1/classes/{class_id}/insights")

        assert resp.status_code == 403, resp.text
        assert resp.json()["error"]["code"] == "FORBIDDEN"

    @pytest.mark.asyncio
    async def test_get_insights_returns_200_for_own_class(
        self, db_session: AsyncSession, pg_dsn: str
    ) -> None:
        """GET /classes/{classId}/insights returns 200 for the owning teacher."""
        teacher_id = _uuid()
        class_id = _uuid()

        await _seed_teacher(db_session, teacher_id)
        await _seed_class(db_session, class_id, teacher_id)

        client = _client_for(teacher_id, pg_dsn)
        resp = client.get(f"/api/v1/classes/{class_id}/insights")

        # No essays exist yet — service returns an empty-data insights object,
        # not an error.
        assert resp.status_code == 200, resp.text
        assert "data" in resp.json()
