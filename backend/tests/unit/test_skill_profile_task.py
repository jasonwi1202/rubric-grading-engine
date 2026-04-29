"""Unit tests for app/tasks/skill_profile.py and the M5-03 aggregation logic.

Tests cover:
- Task registration in Celery.
- Aggregation math: weighted average score calculation.
- Trend calculation: improving, stable, declining, single data point.
- Task happy-path: resolves student, calls compute_and_upsert_skill_profile.
- Task skips gracefully when essay has no student assignment.
- Task skips gracefully when grade is not found or access is denied.
- Transient errors trigger retry with exponential backoff.
- Exhausted retries re-raise and mark the task FAILURE.
- Tenant isolation: task payload with a different teacher's grade is denied.
- Lock-trigger: lock_grade enqueues update_skill_profile task.

No student PII in any fixture.  All database and broker calls are mocked.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.exceptions import ForbiddenError, NotFoundError
from app.services.student_skill_profile import _aggregate_skill_scores, _compute_trend
from app.tasks.celery_app import celery
from app.tasks.skill_profile import (
    _run_update_skill_profile,
    update_skill_profile,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_snapshot(*names_and_ranges: tuple[str, int, int]) -> dict[str, Any]:
    """Build a minimal rubric_snapshot with the given (name, min, max) tuples."""
    criteria = [
        {
            "id": str(uuid.uuid4()),
            "name": name,
            "min_score": min_s,
            "max_score": max_s,
            "weight": 100.0 / len(names_and_ranges),
        }
        for name, min_s, max_s in names_and_ranges
    ]
    return {"criteria": criteria}


def _make_assignment_row(
    snapshot: dict[str, Any],
    scores: list[tuple[uuid.UUID, int]],
    locked_at: datetime | None = None,
) -> dict[str, Any]:
    return {
        "locked_at": locked_at or datetime.now(UTC),
        "rubric_snapshot": snapshot,
        "criterion_scores": scores,
    }


# ---------------------------------------------------------------------------
# Tests — _compute_trend
# ---------------------------------------------------------------------------


class TestComputeTrend:
    def test_single_score_is_stable(self) -> None:
        assert _compute_trend([0.5]) == "stable"

    def test_two_scores_improving(self) -> None:
        assert _compute_trend([0.4, 0.8]) == "improving"

    def test_two_scores_declining(self) -> None:
        assert _compute_trend([0.9, 0.4]) == "declining"

    def test_two_scores_stable_within_threshold(self) -> None:
        # Difference of 0.03 is below the 0.05 threshold.
        assert _compute_trend([0.5, 0.53]) == "stable"

    def test_four_scores_improving(self) -> None:
        # First half [0.3, 0.4] avg=0.35; last half [0.7, 0.8] avg=0.75
        assert _compute_trend([0.3, 0.4, 0.7, 0.8]) == "improving"

    def test_four_scores_declining(self) -> None:
        # First half avg=0.75; last half avg=0.35
        assert _compute_trend([0.8, 0.7, 0.4, 0.3]) == "declining"

    def test_four_scores_stable(self) -> None:
        assert _compute_trend([0.5, 0.5, 0.5, 0.52]) == "stable"

    def test_empty_list_is_stable(self) -> None:
        assert _compute_trend([]) == "stable"


# ---------------------------------------------------------------------------
# Tests — _aggregate_skill_scores
# ---------------------------------------------------------------------------


class TestAggregateSkillScores:
    def test_empty_rows_returns_empty_scores_and_zero_count(self) -> None:
        scores, count = _aggregate_skill_scores([])
        assert scores == {}
        assert count == 0

    def test_single_assignment_single_criterion(self) -> None:
        """A single thesis criterion maps to 'thesis' with stable trend."""
        snapshot = _make_snapshot(("Thesis Statement", 0, 4))
        crit_id = uuid.UUID(snapshot["criteria"][0]["id"])
        row = _make_assignment_row(snapshot, [(crit_id, 4)])

        scores, count = _aggregate_skill_scores([row])

        assert count == 1
        assert "thesis" in scores
        assert scores["thesis"]["avg_score"] == pytest.approx(1.0)
        assert scores["thesis"]["trend"] == "stable"
        assert scores["thesis"]["data_points"] == 1

    def test_weighted_average_favours_recent_assignment(self) -> None:
        """Recency weighting: assignment 1 weight=1, assignment 2 weight=2."""
        snapshot = _make_snapshot(("Grammar", 0, 4))
        crit_id = uuid.UUID(snapshot["criteria"][0]["id"])

        older = _make_assignment_row(
            snapshot,
            [(crit_id, 0)],  # score 0.0 normalised
            locked_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        newer = _make_assignment_row(
            snapshot,
            [(crit_id, 4)],  # score 1.0 normalised
            locked_at=datetime(2026, 2, 1, tzinfo=UTC),
        )

        scores, count = _aggregate_skill_scores([older, newer])

        assert count == 2
        # weight 1 * 0.0 + weight 2 * 1.0 = 2 / 3 ≈ 0.6667
        assert scores["mechanics"]["avg_score"] == pytest.approx(2 / 3, rel=1e-3)

    def test_multiple_criteria_same_skill_averaged_within_assignment(self) -> None:
        """Two criteria both mapping to 'thesis' are averaged within the assignment."""
        snapshot = {
            "criteria": [
                {
                    "id": str(uuid.uuid4()),
                    "name": "Thesis Statement",
                    "min_score": 0,
                    "max_score": 4,
                    "weight": 50,
                },
                {
                    "id": str(uuid.uuid4()),
                    "name": "Main Argument",
                    "min_score": 0,
                    "max_score": 4,
                    "weight": 50,
                },
            ]
        }
        crit_id_1 = uuid.UUID(snapshot["criteria"][0]["id"])
        crit_id_2 = uuid.UUID(snapshot["criteria"][1]["id"])

        row = _make_assignment_row(snapshot, [(crit_id_1, 4), (crit_id_2, 0)])  # avg=0.5

        scores, count = _aggregate_skill_scores([row])

        assert scores["thesis"]["avg_score"] == pytest.approx(0.5)
        # Both criterion scores count as data points.
        assert scores["thesis"]["data_points"] == 2

    def test_improving_trend_over_three_assignments(self) -> None:
        snapshot = _make_snapshot(("Evidence Use", 0, 10))
        cid = uuid.UUID(snapshot["criteria"][0]["id"])

        rows = [
            _make_assignment_row(snapshot, [(cid, 2)], datetime(2026, 1, 1, tzinfo=UTC)),
            _make_assignment_row(snapshot, [(cid, 5)], datetime(2026, 2, 1, tzinfo=UTC)),
            _make_assignment_row(snapshot, [(cid, 9)], datetime(2026, 3, 1, tzinfo=UTC)),
        ]

        scores, _ = _aggregate_skill_scores(rows)
        assert scores["evidence"]["trend"] == "improving"

    def test_declining_trend_over_three_assignments(self) -> None:
        snapshot = _make_snapshot(("Organization", 0, 10))
        cid = uuid.UUID(snapshot["criteria"][0]["id"])

        rows = [
            _make_assignment_row(snapshot, [(cid, 9)], datetime(2026, 1, 1, tzinfo=UTC)),
            _make_assignment_row(snapshot, [(cid, 5)], datetime(2026, 2, 1, tzinfo=UTC)),
            _make_assignment_row(snapshot, [(cid, 1)], datetime(2026, 3, 1, tzinfo=UTC)),
        ]

        scores, _ = _aggregate_skill_scores(rows)
        assert scores["organization"]["trend"] == "declining"

    def test_unmapped_criterion_stored_under_other(self) -> None:
        """A criterion name that does not map to any canonical dimension → 'other'."""
        snapshot = _make_snapshot(("Completely Unknown Criterion XYZ", 0, 5))
        cid = uuid.UUID(snapshot["criteria"][0]["id"])
        row = _make_assignment_row(snapshot, [(cid, 5)])

        scores, _ = _aggregate_skill_scores([row])
        assert "other" in scores

    def test_score_clamped_to_unit_interval(self) -> None:
        """final_score above max_score is clamped to 1.0."""
        snapshot = _make_snapshot(("Thesis Statement", 0, 4))
        cid = uuid.UUID(snapshot["criteria"][0]["id"])
        row = _make_assignment_row(snapshot, [(cid, 99)])  # wildly out of range

        scores, _ = _aggregate_skill_scores([row])
        assert scores["thesis"]["avg_score"] == pytest.approx(1.0)

    def test_missing_criterion_in_snapshot_is_skipped(self) -> None:
        """A criterion score whose ID does not appear in the snapshot is ignored."""
        snapshot = _make_snapshot(("Thesis Statement", 0, 4))
        unknown_cid = uuid.uuid4()  # not in the snapshot
        row = _make_assignment_row(snapshot, [(unknown_cid, 3)])

        scores, _ = _aggregate_skill_scores([row])
        assert scores == {}

    def test_last_updated_is_iso8601_string(self) -> None:
        snapshot = _make_snapshot(("Voice", 0, 5))
        cid = uuid.UUID(snapshot["criteria"][0]["id"])
        row = _make_assignment_row(snapshot, [(cid, 4)])

        scores, _ = _aggregate_skill_scores([row])
        assert isinstance(scores["voice"]["last_updated"], str)
        # Should parse as a valid datetime (raises ValueError if not).
        datetime.fromisoformat(scores["voice"]["last_updated"])

    def test_assignment_count_equals_number_of_rows(self) -> None:
        snapshot = _make_snapshot(("Thesis Statement", 0, 4))
        cid = uuid.UUID(snapshot["criteria"][0]["id"])
        rows = [
            _make_assignment_row(snapshot, [(cid, 2)], datetime(2026, 1, 1, tzinfo=UTC)),
            _make_assignment_row(snapshot, [(cid, 3)], datetime(2026, 2, 1, tzinfo=UTC)),
            _make_assignment_row(snapshot, [(cid, 4)], datetime(2026, 3, 1, tzinfo=UTC)),
        ]
        _, count = _aggregate_skill_scores(rows)
        assert count == 3


# ---------------------------------------------------------------------------
# Tests — task registration
# ---------------------------------------------------------------------------


class TestUpdateSkillProfileTaskRegistration:
    def test_task_is_registered_in_celery(self) -> None:
        assert "tasks.skill_profile.update_skill_profile" in celery.tasks

    def test_task_has_correct_max_retries(self) -> None:
        assert update_skill_profile.max_retries == 3

    def test_task_name_matches_convention(self) -> None:
        assert update_skill_profile.name == "tasks.skill_profile.update_skill_profile"


# ---------------------------------------------------------------------------
# Tests — _run_update_skill_profile async helper
# ---------------------------------------------------------------------------


class TestRunUpdateSkillProfile:
    @pytest.mark.asyncio
    async def test_resolves_student_and_calls_service(self) -> None:
        """Happy path: grade resolves to a student, service is called once."""
        grade_id = str(uuid.uuid4())
        teacher_id = str(uuid.uuid4())
        student_id = uuid.uuid4()

        profile_mock = MagicMock()

        db_mock = AsyncMock()
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=db_mock)
        cm.__aexit__ = AsyncMock(return_value=False)

        service_called: list[tuple[str, str]] = []

        async def _fake_service(
            db: object,
            teacher_id: uuid.UUID,
            student_id: uuid.UUID,
        ) -> MagicMock:
            service_called.append((str(teacher_id), str(student_id)))
            return profile_mock

        with (
            patch(
                "app.tasks.skill_profile._get_student_id_for_grade",
                new=AsyncMock(return_value=student_id),
            ),
            patch("app.tasks.skill_profile.AsyncSessionLocal", return_value=cm),
            patch(
                "app.services.student_skill_profile.compute_and_upsert_skill_profile",
                side_effect=_fake_service,
            ),
        ):
            await _run_update_skill_profile(grade_id, teacher_id)

        assert len(service_called) == 1

    @pytest.mark.asyncio
    async def test_skips_when_student_id_is_none(self) -> None:
        """When essay has no student, service is never called."""
        grade_id = str(uuid.uuid4())
        teacher_id = str(uuid.uuid4())

        service_called: list[bool] = []

        with (
            patch(
                "app.tasks.skill_profile._get_student_id_for_grade",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "app.services.student_skill_profile.compute_and_upsert_skill_profile",
                side_effect=lambda *a, **kw: service_called.append(True),
            ),
        ):
            await _run_update_skill_profile(grade_id, teacher_id)

        assert len(service_called) == 0

    @pytest.mark.asyncio
    async def test_not_found_error_propagates(self) -> None:
        with (
            patch(
                "app.tasks.skill_profile._get_student_id_for_grade",
                new=AsyncMock(side_effect=NotFoundError("Grade not found.")),
            ),
            pytest.raises(NotFoundError),
        ):
            await _run_update_skill_profile(str(uuid.uuid4()), str(uuid.uuid4()))

    @pytest.mark.asyncio
    async def test_forbidden_error_propagates(self) -> None:
        with (
            patch(
                "app.tasks.skill_profile._get_student_id_for_grade",
                new=AsyncMock(side_effect=ForbiddenError("Access denied.")),
            ),
            pytest.raises(ForbiddenError),
        ):
            await _run_update_skill_profile(str(uuid.uuid4()), str(uuid.uuid4()))


# ---------------------------------------------------------------------------
# Tests — update_skill_profile Celery task (eager execution)
# ---------------------------------------------------------------------------


class TestUpdateSkillProfileTask:
    def test_happy_path_succeeds(self) -> None:
        grade_id = str(uuid.uuid4())
        teacher_id = str(uuid.uuid4())

        with patch("app.tasks.skill_profile.asyncio.run", return_value=None) as mock_run:
            result = update_skill_profile(grade_id, teacher_id)
            assert result is None
            mock_run.assert_called_once()

    def test_not_found_does_not_retry(self) -> None:
        """NotFoundError is swallowed — task succeeds without retry."""
        grade_id = str(uuid.uuid4())
        teacher_id = str(uuid.uuid4())

        with patch(
            "app.tasks.skill_profile._run_update_skill_profile",
            new=AsyncMock(side_effect=NotFoundError("Grade not found.")),
        ):
            result = update_skill_profile.apply(args=[grade_id, teacher_id])

        # Task should succeed (not FAILURE) because NotFoundError is swallowed.
        assert result.successful(), "NotFoundError should be swallowed, task should succeed"

    def test_forbidden_does_not_retry(self) -> None:
        """ForbiddenError is swallowed — task succeeds without retry."""
        grade_id = str(uuid.uuid4())
        teacher_id = str(uuid.uuid4())

        with patch(
            "app.tasks.skill_profile._run_update_skill_profile",
            new=AsyncMock(side_effect=ForbiddenError("Access denied.")),
        ):
            result = update_skill_profile.apply(args=[grade_id, teacher_id])

        assert result.successful(), "ForbiddenError should be swallowed, task should succeed"

    def test_transient_error_triggers_retry_then_fails(self) -> None:
        """A RuntimeError causes retries; after exhaustion the task fails."""
        grade_id = str(uuid.uuid4())
        teacher_id = str(uuid.uuid4())

        with patch(
            "app.tasks.skill_profile._run_update_skill_profile",
            new=AsyncMock(side_effect=RuntimeError("DB unavailable")),
        ):
            result = update_skill_profile.apply(args=[grade_id, teacher_id])

        assert result.failed(), "Task should fail after exhausting retries"

    def test_idempotent_on_second_call(self) -> None:
        """Calling the task a second time with the same arguments succeeds."""
        grade_id = str(uuid.uuid4())
        teacher_id = str(uuid.uuid4())

        with patch(
            "app.tasks.skill_profile.asyncio.run",
            return_value=None,
        ):
            r1 = update_skill_profile(grade_id, teacher_id)
            r2 = update_skill_profile(grade_id, teacher_id)

        assert r1 is None
        assert r2 is None


# ---------------------------------------------------------------------------
# Tests — lock_grade triggers update_skill_profile
# ---------------------------------------------------------------------------


class TestLockGradeTriggersSkillProfileTask:
    """Verify that lock_grade enqueues the update_skill_profile task."""

    @pytest.mark.asyncio
    async def test_task_enqueued_on_first_lock(self) -> None:
        """update_skill_profile.delay is called once when a grade is first locked."""
        from datetime import UTC, datetime
        from decimal import Decimal
        from unittest.mock import AsyncMock, MagicMock, patch

        from app.models.grade import ConfidenceLevel, StrictnessLevel
        from app.services.grade import lock_grade

        grade_id = uuid.uuid4()
        teacher_id = uuid.uuid4()

        grade_mock = MagicMock()
        grade_mock.id = grade_id
        grade_mock.essay_version_id = uuid.uuid4()
        grade_mock.total_score = Decimal("4")
        grade_mock.max_possible_score = Decimal("5")
        grade_mock.summary_feedback = "Good work."
        grade_mock.summary_feedback_edited = None
        grade_mock.strictness = StrictnessLevel.balanced
        grade_mock.ai_model = "gpt-4o"
        grade_mock.prompt_version = "grading-v1"
        grade_mock.is_locked = False
        grade_mock.locked_at = None
        grade_mock.overall_confidence = ConfidenceLevel.high
        grade_mock.created_at = datetime.now(UTC)

        # Simulate the atomic UPDATE returning a row (lock was performed).
        update_result = MagicMock()
        update_result.scalar_one_or_none.return_value = grade_id

        # criterion_scores for response construction.
        cs_result = MagicMock()
        cs_result.scalars.return_value.all.return_value = []

        db = AsyncMock()
        db.add = MagicMock()

        # execute call order:
        #   1. _load_grade_tenant_scoped (returns grade_mock)
        #   2. Atomic UPDATE … RETURNING (update_result)
        #   3. _load_criterion_scores (cs_result)
        grade_result = MagicMock()
        grade_result.scalar_one_or_none.return_value = grade_mock
        db.execute = AsyncMock(side_effect=[grade_result, update_result, cs_result])
        db.refresh = AsyncMock()

        delay_calls: list[tuple[str, str]] = []

        task_mock = MagicMock()
        task_mock.delay = MagicMock(side_effect=lambda gid, tid: delay_calls.append((gid, tid)))

        with (
            patch(
                "app.services.grade.update_skill_profile",
                task_mock,
                create=True,
            ),
            # Patch the lazy import inside lock_grade to return our mock.
            patch.dict(
                "sys.modules",
                {"app.tasks.skill_profile": MagicMock(update_skill_profile=task_mock)},
            ),
        ):
            await lock_grade(db=db, grade_id=grade_id, teacher_id=teacher_id)

        assert len(delay_calls) == 1, "update_skill_profile.delay should be called exactly once"
        assert delay_calls[0] == (str(grade_id), str(teacher_id))

    @pytest.mark.asyncio
    async def test_task_not_enqueued_for_already_locked_grade(self) -> None:
        """Locking an already-locked grade is a no-op — task is NOT enqueued."""
        from datetime import UTC, datetime
        from decimal import Decimal

        from app.models.grade import ConfidenceLevel, StrictnessLevel
        from app.services.grade import lock_grade

        grade_id = uuid.uuid4()
        teacher_id = uuid.uuid4()

        grade_mock = MagicMock()
        grade_mock.id = grade_id
        grade_mock.essay_version_id = uuid.uuid4()
        grade_mock.total_score = Decimal("4")
        grade_mock.max_possible_score = Decimal("5")
        grade_mock.summary_feedback = "Good work."
        grade_mock.summary_feedback_edited = None
        grade_mock.strictness = StrictnessLevel.balanced
        grade_mock.ai_model = "gpt-4o"
        grade_mock.prompt_version = "grading-v1"
        grade_mock.is_locked = True  # Already locked
        grade_mock.locked_at = datetime.now(UTC)
        grade_mock.overall_confidence = ConfidenceLevel.high
        grade_mock.created_at = datetime.now(UTC)

        # Atomic UPDATE returns None → grade was already locked.
        update_result = MagicMock()
        update_result.scalar_one_or_none.return_value = None

        cs_result = MagicMock()
        cs_result.scalars.return_value.all.return_value = []

        db = AsyncMock()
        db.add = MagicMock()

        grade_result = MagicMock()
        grade_result.scalar_one_or_none.return_value = grade_mock
        db.execute = AsyncMock(side_effect=[grade_result, update_result, cs_result])
        db.refresh = AsyncMock()

        delay_calls: list[bool] = []
        task_mock = MagicMock()
        task_mock.delay = MagicMock(side_effect=lambda *a: delay_calls.append(True))

        with patch.dict(
            "sys.modules",
            {"app.tasks.skill_profile": MagicMock(update_skill_profile=task_mock)},
        ):
            await lock_grade(db=db, grade_id=grade_id, teacher_id=teacher_id)

        assert len(delay_calls) == 0, "Task must not be enqueued for an already-locked grade"

    @pytest.mark.asyncio
    async def test_broker_failure_does_not_fail_lock(self) -> None:
        """A broker outage when enqueuing must not prevent the lock response."""
        from datetime import UTC, datetime
        from decimal import Decimal

        from app.models.grade import ConfidenceLevel, StrictnessLevel
        from app.services.grade import lock_grade

        grade_id = uuid.uuid4()
        teacher_id = uuid.uuid4()

        grade_mock = MagicMock()
        grade_mock.id = grade_id
        grade_mock.essay_version_id = uuid.uuid4()
        grade_mock.total_score = Decimal("4")
        grade_mock.max_possible_score = Decimal("5")
        grade_mock.summary_feedback = "Good work."
        grade_mock.summary_feedback_edited = None
        grade_mock.strictness = StrictnessLevel.balanced
        grade_mock.ai_model = "gpt-4o"
        grade_mock.prompt_version = "grading-v1"
        grade_mock.is_locked = False
        grade_mock.locked_at = None
        grade_mock.overall_confidence = ConfidenceLevel.high
        grade_mock.created_at = datetime.now(UTC)

        update_result = MagicMock()
        update_result.scalar_one_or_none.return_value = grade_id

        cs_result = MagicMock()
        cs_result.scalars.return_value.all.return_value = []

        db = AsyncMock()
        db.add = MagicMock()

        grade_result = MagicMock()
        grade_result.scalar_one_or_none.return_value = grade_mock
        db.execute = AsyncMock(side_effect=[grade_result, update_result, cs_result])
        db.refresh = AsyncMock()

        task_mock = MagicMock()
        task_mock.delay = MagicMock(side_effect=ConnectionError("Broker down"))

        with patch.dict(
            "sys.modules",
            {"app.tasks.skill_profile": MagicMock(update_skill_profile=task_mock)},
        ):
            # Should NOT raise despite broker failure.
            response = await lock_grade(db=db, grade_id=grade_id, teacher_id=teacher_id)

        assert response.is_locked is True


# ---------------------------------------------------------------------------
# Tests — tenant isolation
# ---------------------------------------------------------------------------


class TestTenantIsolation:
    @pytest.mark.asyncio
    async def test_get_student_id_raises_forbidden_for_wrong_teacher(self) -> None:
        """_get_student_id_for_grade raises ForbiddenError when grade belongs to another teacher."""
        from app.tasks.skill_profile import _get_student_id_for_grade

        grade_id = uuid.uuid4()
        teacher_id = uuid.uuid4()

        db_mock = AsyncMock()

        # First execute: tenant-scoped query returns nothing (grade exists but
        # belongs to a different teacher).
        scoped_result = MagicMock()
        scoped_result.one_or_none.return_value = None

        # Second execute (existence check): returns a row so we know it's 403 not 404.
        exists_result = MagicMock()
        exists_result.scalar_one_or_none.return_value = grade_id

        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=db_mock)
        cm.__aexit__ = AsyncMock(return_value=False)

        db_mock.execute = AsyncMock(side_effect=[scoped_result, exists_result])

        with (
            patch("app.tasks.skill_profile.AsyncSessionLocal", return_value=cm),
            pytest.raises(ForbiddenError),
        ):
            await _get_student_id_for_grade(grade_id, teacher_id)

    @pytest.mark.asyncio
    async def test_get_student_id_raises_not_found_for_missing_grade(self) -> None:
        """_get_student_id_for_grade raises NotFoundError when grade does not exist."""
        from app.tasks.skill_profile import _get_student_id_for_grade

        grade_id = uuid.uuid4()
        teacher_id = uuid.uuid4()

        db_mock = AsyncMock()

        scoped_result = MagicMock()
        scoped_result.one_or_none.return_value = None

        exists_result = MagicMock()
        exists_result.scalar_one_or_none.return_value = None  # grade doesn't exist

        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=db_mock)
        cm.__aexit__ = AsyncMock(return_value=False)

        db_mock.execute = AsyncMock(side_effect=[scoped_result, exists_result])

        with (
            patch("app.tasks.skill_profile.AsyncSessionLocal", return_value=cm),
            pytest.raises(NotFoundError),
        ):
            await _get_student_id_for_grade(grade_id, teacher_id)
