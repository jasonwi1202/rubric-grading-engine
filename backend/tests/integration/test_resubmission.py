"""Integration tests for POST /essays/{essayId}/resubmit (M6-10).

Tests exercise the full stack: real PostgreSQL (via testcontainers),
Alembic-migrated schema, real ORM writes, mocked S3 / MIME / extraction.
Auth is injected via FastAPI dependency override.

Covered scenarios:
  - Happy path: 201 + new EssayVersion row with version_number = 2
  - Resubmission disabled: 409 RESUBMISSION_DISABLED
  - Resubmission limit reached: 409 RESUBMISSION_LIMIT_REACHED
  - Cross-teacher access: 403 FORBIDDEN
  - Essay not found: 404 NOT_FOUND

Tests skip automatically if Docker is not available.
No student PII in any fixture.
"""

from __future__ import annotations

import io
import json
import uuid
from collections.abc import AsyncGenerator
from unittest.mock import MagicMock, patch

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


# ---------------------------------------------------------------------------
# Seeding helpers — no student PII in any literal value
# ---------------------------------------------------------------------------


async def _seed_teacher(db: AsyncSession, teacher_id: uuid.UUID) -> None:
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
    db: AsyncSession, class_id: uuid.UUID, teacher_id: uuid.UUID
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


async def _seed_rubric(
    db: AsyncSession, rubric_id: uuid.UUID, teacher_id: uuid.UUID
) -> None:
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
    *,
    resubmission_enabled: bool = True,
    resubmission_limit: int | None = None,
) -> None:
    snapshot = json.dumps({"criteria": []})
    await db.execute(
        text(
            "INSERT INTO assignments "
            "(id, class_id, rubric_id, rubric_snapshot, title, status, "
            "resubmission_enabled, resubmission_limit) "
            "VALUES (:id, :cid, :rid, CAST(:snap AS jsonb), :title, 'open', "
            ":re_enabled, :re_limit) ON CONFLICT DO NOTHING"
        ),
        {
            "id": str(assignment_id),
            "cid": str(class_id),
            "rid": str(rubric_id),
            "snap": snapshot,
            "title": "Test Assignment",
            "re_enabled": resubmission_enabled,
            "re_limit": resubmission_limit,
        },
    )
    await db.commit()


async def _seed_essay(
    db: AsyncSession,
    essay_id: uuid.UUID,
    assignment_id: uuid.UUID,
) -> None:
    await db.execute(
        text(
            "INSERT INTO essays (id, assignment_id, status) "
            "VALUES (:id, :aid, 'unassigned') ON CONFLICT DO NOTHING"
        ),
        {"id": str(essay_id), "aid": str(assignment_id)},
    )
    await db.commit()


async def _seed_essay_version(
    db: AsyncSession,
    version_id: uuid.UUID,
    essay_id: uuid.UUID,
    version_number: int = 1,
) -> None:
    await db.execute(
        text(
            "INSERT INTO essay_versions "
            "(id, essay_id, version_number, content, word_count) "
            "VALUES (:id, :eid, :vn, :content, :wc) ON CONFLICT DO NOTHING"
        ),
        {
            "id": str(version_id),
            "eid": str(essay_id),
            "vn": version_number,
            "content": "Original submission text for testing.",
            "wc": 6,
        },
    )
    await db.commit()


# ---------------------------------------------------------------------------
# Integration test class
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestResubmitEssayIntegration:
    """Integration tests for POST /essays/{essayId}/resubmit."""

    def _upload_file(self) -> tuple[str, io.BytesIO, str]:
        """Return (field_name, file_bytes, filename) for multipart upload."""
        content = b"This is a revised essay for integration testing."
        return ("file", io.BytesIO(content), "revision.txt")

    @pytest.mark.asyncio
    async def test_happy_path_creates_new_version(
        self, db_session: AsyncSession, pg_dsn: str
    ) -> None:
        """POST creates a new EssayVersion with version_number = 2."""
        teacher_id = _uuid()
        class_id = _uuid()
        rubric_id = _uuid()
        assignment_id = _uuid()
        essay_id = _uuid()
        version_id = _uuid()

        await _seed_teacher(db_session, teacher_id)
        await _seed_class(db_session, class_id, teacher_id)
        await _seed_rubric(db_session, rubric_id, teacher_id)
        await _seed_assignment(
            db_session,
            assignment_id,
            class_id,
            rubric_id,
            resubmission_enabled=True,
        )
        await _seed_essay(db_session, essay_id, assignment_id)
        await _seed_essay_version(db_session, version_id, essay_id, version_number=1)

        client = _client_for(teacher_id, pg_dsn)
        field, data, filename = self._upload_file()

        with (
            patch("app.services.essay.validate_mime_type", return_value="text/plain"),
            patch("app.services.essay.upload_file"),
            patch(
                "app.services.essay.extract_text",
                return_value="Revised essay content for integration testing.",
            ),
            patch("app.routers.essays._compute_embedding_task") as mock_embedding_task,
        ):
            resp = client.post(
                f"/api/v1/essays/{essay_id}/resubmit",
                files={field: (filename, data, "text/plain")},
            )

        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert "data" in body
        result = body["data"]
        assert result["essay_id"] == str(essay_id)
        assert result["assignment_id"] == str(assignment_id)
        assert result["version_number"] == 2

        # Verify embedding task was enqueued for the new version.
        mock_embedding_task.delay.assert_called_once()
        call_args = mock_embedding_task.delay.call_args[0]
        assert call_args[0] == result["essay_version_id"]
        assert call_args[1] == str(assignment_id)
        assert call_args[2] == str(teacher_id)

        # Verify the new row was written to the DB.
        rows = (
            await db_session.execute(
                text(
                    "SELECT version_number FROM essay_versions "
                    "WHERE essay_id = :eid ORDER BY version_number"
                ),
                {"eid": str(essay_id)},
            )
        ).fetchall()
        assert len(rows) == 2
        assert rows[1].version_number == 2

    @pytest.mark.asyncio
    async def test_resubmission_disabled_returns_409(
        self, db_session: AsyncSession, pg_dsn: str
    ) -> None:
        """409 RESUBMISSION_DISABLED when assignment has resubmission_enabled=false."""
        teacher_id = _uuid()
        class_id = _uuid()
        rubric_id = _uuid()
        assignment_id = _uuid()
        essay_id = _uuid()
        version_id = _uuid()

        await _seed_teacher(db_session, teacher_id)
        await _seed_class(db_session, class_id, teacher_id)
        await _seed_rubric(db_session, rubric_id, teacher_id)
        await _seed_assignment(
            db_session,
            assignment_id,
            class_id,
            rubric_id,
            resubmission_enabled=False,
        )
        await _seed_essay(db_session, essay_id, assignment_id)
        await _seed_essay_version(db_session, version_id, essay_id, version_number=1)

        client = _client_for(teacher_id, pg_dsn)
        field, data, filename = self._upload_file()

        with (
            patch("app.services.essay.validate_mime_type", return_value="text/plain"),
            patch("app.services.essay.upload_file"),
            patch(
                "app.services.essay.extract_text",
                return_value="Revised essay content.",
            ),
        ):
            resp = client.post(
                f"/api/v1/essays/{essay_id}/resubmit",
                files={field: (filename, data, "text/plain")},
            )

        assert resp.status_code == 409, resp.text
        body = resp.json()
        assert body.get("error", {}).get("code") == "RESUBMISSION_DISABLED"

    @pytest.mark.asyncio
    async def test_resubmission_limit_reached_returns_409(
        self, db_session: AsyncSession, pg_dsn: str
    ) -> None:
        """409 RESUBMISSION_LIMIT_REACHED when limit has been exhausted."""
        teacher_id = _uuid()
        class_id = _uuid()
        rubric_id = _uuid()
        assignment_id = _uuid()
        essay_id = _uuid()
        version1_id = _uuid()
        version2_id = _uuid()

        await _seed_teacher(db_session, teacher_id)
        await _seed_class(db_session, class_id, teacher_id)
        await _seed_rubric(db_session, rubric_id, teacher_id)
        # limit = 1; original (v1) + one resubmission (v2) already present.
        await _seed_assignment(
            db_session,
            assignment_id,
            class_id,
            rubric_id,
            resubmission_enabled=True,
            resubmission_limit=1,
        )
        await _seed_essay(db_session, essay_id, assignment_id)
        await _seed_essay_version(db_session, version1_id, essay_id, version_number=1)
        await _seed_essay_version(db_session, version2_id, essay_id, version_number=2)

        client = _client_for(teacher_id, pg_dsn)
        field, data, filename = self._upload_file()

        with (
            patch("app.services.essay.validate_mime_type", return_value="text/plain"),
            patch("app.services.essay.upload_file"),
            patch(
                "app.services.essay.extract_text",
                return_value="Another revision attempt.",
            ),
        ):
            resp = client.post(
                f"/api/v1/essays/{essay_id}/resubmit",
                files={field: (filename, data, "text/plain")},
            )

        assert resp.status_code == 409, resp.text
        body = resp.json()
        assert body.get("error", {}).get("code") == "RESUBMISSION_LIMIT_REACHED"

    @pytest.mark.asyncio
    async def test_cross_teacher_returns_403(
        self, db_session: AsyncSession, pg_dsn: str
    ) -> None:
        """Teacher B cannot resubmit an essay belonging to Teacher A."""
        teacher_a_id = _uuid()
        teacher_b_id = _uuid()
        class_id = _uuid()
        rubric_id = _uuid()
        assignment_id = _uuid()
        essay_id = _uuid()
        version_id = _uuid()

        await _seed_teacher(db_session, teacher_a_id)
        await _seed_teacher(db_session, teacher_b_id)
        await _seed_class(db_session, class_id, teacher_a_id)
        await _seed_rubric(db_session, rubric_id, teacher_a_id)
        await _seed_assignment(
            db_session,
            assignment_id,
            class_id,
            rubric_id,
            resubmission_enabled=True,
        )
        await _seed_essay(db_session, essay_id, assignment_id)
        await _seed_essay_version(db_session, version_id, essay_id, version_number=1)

        # Teacher B attempts to resubmit Teacher A's essay.
        client = _client_for(teacher_b_id, pg_dsn)
        field, data, filename = self._upload_file()

        with (
            patch("app.services.essay.validate_mime_type", return_value="text/plain"),
            patch("app.services.essay.upload_file"),
            patch(
                "app.services.essay.extract_text",
                return_value="Unauthorized revision attempt.",
            ),
        ):
            resp = client.post(
                f"/api/v1/essays/{essay_id}/resubmit",
                files={field: (filename, data, "text/plain")},
            )

        assert resp.status_code == 403, resp.text

    @pytest.mark.asyncio
    async def test_essay_not_found_returns_404(
        self, db_session: AsyncSession, pg_dsn: str
    ) -> None:
        """404 when the essay UUID does not exist."""
        teacher_id = _uuid()
        await _seed_teacher(db_session, teacher_id)

        client = _client_for(teacher_id, pg_dsn)
        nonexistent_essay_id = _uuid()
        field, data, filename = self._upload_file()

        with (
            patch("app.services.essay.validate_mime_type", return_value="text/plain"),
            patch("app.services.essay.upload_file"),
            patch("app.services.essay.extract_text", return_value="content"),
        ):
            resp = client.post(
                f"/api/v1/essays/{nonexistent_essay_id}/resubmit",
                files={field: (filename, data, "text/plain")},
            )

        assert resp.status_code == 404, resp.text
