"""Unit tests for the StudentSkillProfile ORM model and upsert service.

Tests verify:
- The model imports without errors and declares the expected table name.
- All required columns are present with the correct nullability and type.
- The unique constraint on (teacher_id, student_id) is declared.
- The migration revision module is wired correctly into the Alembic chain.
- The upsert service function raises the correct domain exceptions.
- Tenant isolation: a teacher cannot read or overwrite another teacher's profile.

No real database connection is needed for model-structure tests — SQLAlchemy
populates metadata at import time.

Service tests use mocked AsyncSession objects so no database or broker is
required.

No student PII appears in any fixture or assertion.
"""

from __future__ import annotations

import importlib
import uuid
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.exceptions import ForbiddenError, NotFoundError
from app.models.base import Base
from app.models.student_skill_profile import StudentSkillProfile

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _col(model: type, name: str) -> object:
    """Return the Column object from Base.metadata for a given model + column name."""
    table = Base.metadata.tables[model.__tablename__]  # type: ignore[attr-defined]
    assert name in table.c, f"Column '{name}' not found in table '{model.__tablename__}'"
    return table.c[name]


def _is_nullable(model: type, name: str) -> bool:
    col = _col(model, name)
    return col.nullable  # type: ignore[union-attr]


def _type_name(model: type, name: str) -> str:
    col = _col(model, name)
    return type(col.type).__name__  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# Model structure tests
# ---------------------------------------------------------------------------


class TestStudentSkillProfileModel:
    def test_tablename(self) -> None:
        assert StudentSkillProfile.__tablename__ == "student_skill_profiles"

    def test_expected_columns_present(self) -> None:
        table = Base.metadata.tables["student_skill_profiles"]
        expected = {
            "id",
            "teacher_id",
            "student_id",
            "skill_scores",
            "assignment_count",
            "last_updated_at",
            "created_at",
        }
        assert expected <= set(table.c.keys()), f"Missing columns: {expected - set(table.c.keys())}"

    def test_teacher_id_not_nullable(self) -> None:
        assert not _is_nullable(StudentSkillProfile, "teacher_id")

    def test_student_id_not_nullable(self) -> None:
        assert not _is_nullable(StudentSkillProfile, "student_id")

    def test_skill_scores_not_nullable(self) -> None:
        assert not _is_nullable(StudentSkillProfile, "skill_scores")

    def test_skill_scores_is_jsonb(self) -> None:
        assert _type_name(StudentSkillProfile, "skill_scores") == "JSONB"

    def test_assignment_count_not_nullable(self) -> None:
        assert not _is_nullable(StudentSkillProfile, "assignment_count")

    def test_assignment_count_is_integer(self) -> None:
        assert _type_name(StudentSkillProfile, "assignment_count") == "Integer"

    def test_last_updated_at_not_nullable(self) -> None:
        assert not _is_nullable(StudentSkillProfile, "last_updated_at")

    def test_created_at_not_nullable(self) -> None:
        assert not _is_nullable(StudentSkillProfile, "created_at")

    def test_unique_constraint_teacher_student(self) -> None:
        """There must be a unique constraint on (teacher_id, student_id)."""
        table = Base.metadata.tables["student_skill_profiles"]
        found = False
        for constraint in table.constraints:
            if hasattr(constraint, "columns"):
                col_names = {c.name for c in constraint.columns}
                if col_names == {"teacher_id", "student_id"}:
                    found = True
                    break
        assert found, (
            "Expected a UniqueConstraint on (teacher_id, student_id) in student_skill_profiles."
        )


# ---------------------------------------------------------------------------
# Migration revision chain
# ---------------------------------------------------------------------------


class TestMigrationRevisionChain:
    def test_revision_id(self) -> None:
        mod = importlib.import_module(
            "app.db.migrations.versions.20260427_022_student_skill_profiles_create_table"
        )
        assert mod.revision == "022_student_skill_profiles"

    def test_down_revision_points_to_021(self) -> None:
        mod = importlib.import_module(
            "app.db.migrations.versions.20260427_022_student_skill_profiles_create_table"
        )
        assert mod.down_revision == "021_grades_prompt_version"

    def test_upgrade_callable(self) -> None:
        mod = importlib.import_module(
            "app.db.migrations.versions.20260427_022_student_skill_profiles_create_table"
        )
        assert callable(mod.upgrade)

    def test_downgrade_callable(self) -> None:
        mod = importlib.import_module(
            "app.db.migrations.versions.20260427_022_student_skill_profiles_create_table"
        )
        assert callable(mod.downgrade)


# ---------------------------------------------------------------------------
# Service-layer unit tests (mocked AsyncSession)
# ---------------------------------------------------------------------------

# Canonical skill_scores payload used across service tests.
_SKILL_SCORES: dict[str, Any] = {
    "thesis": {
        "avg_score": 0.85,
        "trend": "improving",
        "data_points": 3,
        "last_updated": "2026-04-27T00:00:00+00:00",
    },
    "evidence": {
        "avg_score": 0.70,
        "trend": "stable",
        "data_points": 3,
        "last_updated": "2026-04-27T00:00:00+00:00",
    },
}


def _make_student_row(
    student_id: uuid.UUID,
    teacher_id: uuid.UUID,
) -> MagicMock:
    row = MagicMock()
    row.id = student_id
    row.teacher_id = teacher_id
    return row


def _make_profile(
    teacher_id: uuid.UUID,
    student_id: uuid.UUID,
) -> StudentSkillProfile:
    profile = StudentSkillProfile()
    profile.id = uuid.uuid4()
    profile.teacher_id = teacher_id
    profile.student_id = student_id
    profile.skill_scores = _SKILL_SCORES
    profile.assignment_count = 3
    profile.last_updated_at = datetime.now(UTC)
    profile.created_at = datetime.now(UTC)
    return profile


class TestGetSkillProfile:
    """Tests for ``student_skill_profile.get_skill_profile``."""

    @pytest.mark.asyncio
    async def test_returns_profile_for_valid_teacher_student(self) -> None:
        from app.services.student_skill_profile import get_skill_profile

        teacher_id = uuid.uuid4()
        student_id = uuid.uuid4()
        profile = _make_profile(teacher_id, student_id)

        db = AsyncMock()
        student_row = _make_student_row(student_id, teacher_id)

        # First execute: student lookup; second execute: profile lookup.
        student_result = MagicMock()
        student_result.one_or_none.return_value = student_row
        profile_result = MagicMock()
        profile_result.scalar_one_or_none.return_value = profile
        db.execute = AsyncMock(side_effect=[student_result, profile_result])

        result = await get_skill_profile(db, teacher_id, student_id)
        assert result is profile

    @pytest.mark.asyncio
    async def test_raises_not_found_when_student_missing(self) -> None:
        from app.services.student_skill_profile import get_skill_profile

        teacher_id = uuid.uuid4()
        student_id = uuid.uuid4()

        db = AsyncMock()
        student_result = MagicMock()
        student_result.one_or_none.return_value = None
        db.execute = AsyncMock(return_value=student_result)

        with pytest.raises(NotFoundError):
            await get_skill_profile(db, teacher_id, student_id)

    @pytest.mark.asyncio
    async def test_raises_forbidden_for_wrong_teacher(self) -> None:
        from app.services.student_skill_profile import get_skill_profile

        teacher_a = uuid.uuid4()
        teacher_b = uuid.uuid4()
        student_id = uuid.uuid4()

        db = AsyncMock()
        student_row = _make_student_row(student_id, teacher_a)
        student_result = MagicMock()
        student_result.one_or_none.return_value = student_row
        db.execute = AsyncMock(return_value=student_result)

        with pytest.raises(ForbiddenError):
            await get_skill_profile(db, teacher_b, student_id)

    @pytest.mark.asyncio
    async def test_raises_not_found_when_profile_missing(self) -> None:
        from app.services.student_skill_profile import get_skill_profile

        teacher_id = uuid.uuid4()
        student_id = uuid.uuid4()

        db = AsyncMock()
        student_row = _make_student_row(student_id, teacher_id)
        student_result = MagicMock()
        student_result.one_or_none.return_value = student_row
        profile_result = MagicMock()
        profile_result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(side_effect=[student_result, profile_result])

        with pytest.raises(NotFoundError):
            await get_skill_profile(db, teacher_id, student_id)


class TestUpsertSkillProfile:
    """Tests for ``student_skill_profile.upsert_skill_profile``."""

    @pytest.mark.asyncio
    async def test_upsert_returns_profile_on_insert(self) -> None:
        from app.services.student_skill_profile import upsert_skill_profile

        teacher_id = uuid.uuid4()
        student_id = uuid.uuid4()
        profile = _make_profile(teacher_id, student_id)

        db = AsyncMock()
        student_row = _make_student_row(student_id, teacher_id)
        student_result = MagicMock()
        student_result.one_or_none.return_value = student_row

        upsert_result = MagicMock()
        upsert_result.scalar_one.return_value = profile.id

        reload_result = MagicMock()
        reload_result.scalar_one.return_value = profile

        db.execute = AsyncMock(side_effect=[student_result, upsert_result, reload_result])

        result = await upsert_skill_profile(
            db,
            teacher_id,
            student_id,
            skill_scores=_SKILL_SCORES,
            assignment_count=3,
        )
        assert result is profile
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_upsert_raises_not_found_for_missing_student(self) -> None:
        from app.services.student_skill_profile import upsert_skill_profile

        teacher_id = uuid.uuid4()
        student_id = uuid.uuid4()

        db = AsyncMock()
        student_result = MagicMock()
        student_result.one_or_none.return_value = None
        db.execute = AsyncMock(return_value=student_result)

        with pytest.raises(NotFoundError):
            await upsert_skill_profile(
                db,
                teacher_id,
                student_id,
                skill_scores=_SKILL_SCORES,
                assignment_count=1,
            )

    @pytest.mark.asyncio
    async def test_upsert_raises_forbidden_for_wrong_teacher(self) -> None:
        from app.services.student_skill_profile import upsert_skill_profile

        teacher_a = uuid.uuid4()
        teacher_b = uuid.uuid4()
        student_id = uuid.uuid4()

        db = AsyncMock()
        student_row = _make_student_row(student_id, teacher_a)
        student_result = MagicMock()
        student_result.one_or_none.return_value = student_row
        db.execute = AsyncMock(return_value=student_result)

        with pytest.raises(ForbiddenError):
            await upsert_skill_profile(
                db,
                teacher_b,
                student_id,
                skill_scores=_SKILL_SCORES,
                assignment_count=1,
            )

    @pytest.mark.asyncio
    async def test_upsert_updates_existing_profile(self) -> None:
        """A second upsert with new scores overwrites the previous values."""
        from app.services.student_skill_profile import upsert_skill_profile

        teacher_id = uuid.uuid4()
        student_id = uuid.uuid4()

        updated_scores: dict[str, Any] = {
            "thesis": {
                "avg_score": 0.90,
                "trend": "improving",
                "data_points": 5,
                "last_updated": "2026-04-27T01:00:00+00:00",
            },
        }
        updated_profile = _make_profile(teacher_id, student_id)
        updated_profile.skill_scores = updated_scores
        updated_profile.assignment_count = 5

        db = AsyncMock()
        student_row = _make_student_row(student_id, teacher_id)
        student_result = MagicMock()
        student_result.one_or_none.return_value = student_row

        upsert_result = MagicMock()
        upsert_result.scalar_one.return_value = updated_profile.id

        reload_result = MagicMock()
        reload_result.scalar_one.return_value = updated_profile

        db.execute = AsyncMock(side_effect=[student_result, upsert_result, reload_result])

        result = await upsert_skill_profile(
            db,
            teacher_id,
            student_id,
            skill_scores=updated_scores,
            assignment_count=5,
        )
        assert result.skill_scores == updated_scores
        assert result.assignment_count == 5
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_upsert_tenant_isolation_different_teachers(self) -> None:
        """Two teachers with the same student_id UUID cannot cross-contaminate.

        In practice the student belongs to exactly one teacher, so if teacher B
        tries to upsert a profile for teacher A's student, the ownership check
        raises ForbiddenError before the INSERT is attempted.
        """
        from app.services.student_skill_profile import upsert_skill_profile

        teacher_a = uuid.uuid4()
        teacher_b = uuid.uuid4()
        student_id = uuid.uuid4()

        db = AsyncMock()
        # Student is owned by teacher_a.
        student_row = _make_student_row(student_id, teacher_a)
        student_result = MagicMock()
        student_result.one_or_none.return_value = student_row
        db.execute = AsyncMock(return_value=student_result)

        with pytest.raises(ForbiddenError):
            await upsert_skill_profile(
                db,
                teacher_b,
                student_id,
                skill_scores=_SKILL_SCORES,
                assignment_count=1,
            )

        # Commit must never be called when authorization fails.
        db.commit.assert_not_awaited()
