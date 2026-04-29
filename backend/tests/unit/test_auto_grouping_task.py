"""Unit tests for app/tasks/auto_grouping.py and app/services/auto_grouping.py.

Tests cover:
- Task registration in Celery (name, max_retries).
- Service: _build_groups correctly clusters students by shared underperforming skills.
- Service: min_group_size threshold filters out singleton groups.
- Service: students with no skill profile are skipped.
- Service: skills above the underperformance threshold are excluded.
- Task happy-path: resolves class_id, calls compute_and_persist_groups.
- Task: NotFoundError and ForbiddenError are swallowed (no retry).
- Task: transient errors trigger exponential-backoff retry then FAILURE.
- Task: idempotent on second call.
- Lock-trigger: lock_grade enqueues compute_class_groups task.
- Tenant isolation: task payload with a different teacher's grade is denied.

No student PII in any fixture.  All database and broker calls are mocked.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.exceptions import ForbiddenError, NotFoundError
from app.services.auto_grouping import _build_groups
from app.tasks.auto_grouping import (
    _run_compute_class_groups,
    compute_class_groups,
)
from app.tasks.celery_app import celery

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_profile(
    student_id: uuid.UUID,
    teacher_id: uuid.UUID,
    skills: dict[str, float],
) -> MagicMock:
    """Build a mock StudentSkillProfile with the given avg_scores per skill."""
    skill_scores: dict[str, Any] = {
        skill: {
            "avg_score": score,
            "trend": "stable",
            "data_points": 2,
            "last_updated": "2026-01-01T00:00:00+00:00",
        }
        for skill, score in skills.items()
    }
    profile = MagicMock()
    profile.student_id = student_id
    profile.teacher_id = teacher_id
    profile.skill_scores = skill_scores
    return profile


# ---------------------------------------------------------------------------
# Tests — task registration
# ---------------------------------------------------------------------------


class TestComputeClassGroupsTaskRegistration:
    def test_task_is_registered_in_celery(self) -> None:
        assert "tasks.auto_grouping.compute_class_groups" in celery.tasks

    def test_task_has_correct_max_retries(self) -> None:
        assert compute_class_groups.max_retries == 3

    def test_task_name_matches_convention(self) -> None:
        assert compute_class_groups.name == "tasks.auto_grouping.compute_class_groups"


# ---------------------------------------------------------------------------
# Tests — _build_groups pure function
# ---------------------------------------------------------------------------


class TestBuildGroups:
    def test_empty_profiles_returns_no_groups(self) -> None:
        groups = _build_groups([], underperformance_threshold=0.7, min_group_size=2)
        assert groups == []

    def test_single_student_below_threshold_below_min_size(self) -> None:
        """One student underperforming → group size=1, filtered by min_group_size=2."""
        teacher_id = uuid.uuid4()
        profiles = [_make_profile(uuid.uuid4(), teacher_id, {"evidence": 0.5})]
        groups = _build_groups(profiles, underperformance_threshold=0.7, min_group_size=2)
        assert groups == []

    def test_two_students_same_skill_forms_group(self) -> None:
        """Two students both underperforming in 'thesis' → one group."""
        teacher_id = uuid.uuid4()
        sid1, sid2 = uuid.uuid4(), uuid.uuid4()
        profiles = [
            _make_profile(sid1, teacher_id, {"thesis": 0.4}),
            _make_profile(sid2, teacher_id, {"thesis": 0.6}),
        ]
        groups = _build_groups(profiles, underperformance_threshold=0.7, min_group_size=2)
        assert len(groups) == 1
        assert groups[0]["skill_key"] == "thesis"
        assert set(groups[0]["student_ids"]) == {str(sid1), str(sid2)}
        assert groups[0]["student_count"] == 2

    def test_student_above_threshold_excluded_from_group(self) -> None:
        """A student at or above the threshold is NOT placed in the group."""
        teacher_id = uuid.uuid4()
        sid1, sid2 = uuid.uuid4(), uuid.uuid4()
        profiles = [
            _make_profile(sid1, teacher_id, {"evidence": 0.5}),
            _make_profile(sid2, teacher_id, {"evidence": 0.85}),  # above threshold
        ]
        groups = _build_groups(profiles, underperformance_threshold=0.7, min_group_size=2)
        # Only sid1 is underperforming — group size = 1, filtered
        assert groups == []

    def test_students_in_multiple_groups(self) -> None:
        """Students can appear in several groups if they underperform in several skills."""
        teacher_id = uuid.uuid4()
        sid1, sid2, sid3 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        profiles = [
            _make_profile(sid1, teacher_id, {"evidence": 0.4, "thesis": 0.3}),
            _make_profile(sid2, teacher_id, {"evidence": 0.5, "thesis": 0.6}),
            _make_profile(sid3, teacher_id, {"thesis": 0.5}),  # only in thesis group
        ]
        groups = _build_groups(profiles, underperformance_threshold=0.7, min_group_size=2)
        skill_keys = {g["skill_key"] for g in groups}
        assert "evidence" in skill_keys
        assert "thesis" in skill_keys

        thesis_group = next(g for g in groups if g["skill_key"] == "thesis")
        assert set(thesis_group["student_ids"]) == {str(sid1), str(sid2), str(sid3)}

        evidence_group = next(g for g in groups if g["skill_key"] == "evidence")
        assert set(evidence_group["student_ids"]) == {str(sid1), str(sid2)}

    def test_label_is_title_cased_skill_key(self) -> None:
        """Label is the skill_key with underscores replaced and title-cased."""
        teacher_id = uuid.uuid4()
        profiles = [
            _make_profile(uuid.uuid4(), teacher_id, {"word_choice": 0.5}),
            _make_profile(uuid.uuid4(), teacher_id, {"word_choice": 0.4}),
        ]
        groups = _build_groups(profiles, underperformance_threshold=0.7, min_group_size=2)
        assert len(groups) == 1
        assert groups[0]["label"] == "Word Choice"

    def test_profile_with_no_skill_scores_is_skipped(self) -> None:
        """A profile with empty skill_scores does not raise and produces no groups."""
        teacher_id = uuid.uuid4()
        empty_profile = MagicMock()
        empty_profile.student_id = uuid.uuid4()
        empty_profile.teacher_id = teacher_id
        empty_profile.skill_scores = {}
        groups = _build_groups([empty_profile], underperformance_threshold=0.7, min_group_size=2)
        assert groups == []

    def test_profile_with_none_skill_scores_is_skipped(self) -> None:
        """A profile where skill_scores is None does not raise."""
        teacher_id = uuid.uuid4()
        null_profile = MagicMock()
        null_profile.student_id = uuid.uuid4()
        null_profile.teacher_id = teacher_id
        null_profile.skill_scores = None
        groups = _build_groups([null_profile], underperformance_threshold=0.7, min_group_size=2)
        assert groups == []

    def test_threshold_boundary_strictly_below(self) -> None:
        """avg_score exactly equal to threshold is NOT underperforming."""
        teacher_id = uuid.uuid4()
        sid_at = uuid.uuid4()
        sid_below = uuid.uuid4()
        profiles = [
            _make_profile(sid_at, teacher_id, {"evidence": 0.7}),  # at threshold — excluded
            _make_profile(sid_below, teacher_id, {"evidence": 0.699}),  # below — included
        ]
        # Only sid_below is underperforming → group size=1 → filtered by min_group_size=2
        groups = _build_groups(profiles, underperformance_threshold=0.7, min_group_size=2)
        assert groups == []

    def test_min_group_size_one_includes_singletons(self) -> None:
        """When min_group_size=1, a single underperforming student forms a group."""
        teacher_id = uuid.uuid4()
        sid = uuid.uuid4()
        profiles = [_make_profile(sid, teacher_id, {"evidence": 0.4})]
        groups = _build_groups(profiles, underperformance_threshold=0.7, min_group_size=1)
        assert len(groups) == 1
        assert groups[0]["student_count"] == 1

    def test_computed_at_is_iso8601_string(self) -> None:
        """computed_at in group dict is a valid ISO-8601 string."""
        teacher_id = uuid.uuid4()
        profiles = [
            _make_profile(uuid.uuid4(), teacher_id, {"thesis": 0.3}),
            _make_profile(uuid.uuid4(), teacher_id, {"thesis": 0.4}),
        ]
        groups = _build_groups(profiles, underperformance_threshold=0.7, min_group_size=2)
        assert len(groups) == 1
        datetime.fromisoformat(groups[0]["computed_at"])


# ---------------------------------------------------------------------------
# Tests — _run_compute_class_groups async helper
# ---------------------------------------------------------------------------


class TestRunComputeClassGroups:
    @pytest.mark.asyncio
    async def test_resolves_class_and_calls_service(self) -> None:
        """Happy path: grade resolves to a class, service is called once."""
        grade_id = str(uuid.uuid4())
        teacher_id = str(uuid.uuid4())
        class_id = uuid.uuid4()

        db_mock = AsyncMock()
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=db_mock)
        cm.__aexit__ = AsyncMock(return_value=False)

        service_calls: list[tuple[str, str]] = []

        async def _fake_service(
            db: object,
            teacher_id: uuid.UUID,
            class_id: uuid.UUID,
            *,
            underperformance_threshold: float,
            min_group_size: int,
        ) -> list[object]:
            service_calls.append((str(teacher_id), str(class_id)))
            return []

        with (
            patch(
                "app.tasks.auto_grouping._get_class_id_for_grade",
                new=AsyncMock(return_value=class_id),
            ),
            patch("app.tasks.auto_grouping.AsyncSessionLocal", return_value=cm),
            patch(
                "app.services.auto_grouping.compute_and_persist_groups",
                side_effect=_fake_service,
            ),
        ):
            await _run_compute_class_groups(grade_id, teacher_id)

        assert len(service_calls) == 1

    @pytest.mark.asyncio
    async def test_not_found_error_propagates(self) -> None:
        with (
            patch(
                "app.tasks.auto_grouping._get_class_id_for_grade",
                new=AsyncMock(side_effect=NotFoundError("Grade not found.")),
            ),
            pytest.raises(NotFoundError),
        ):
            await _run_compute_class_groups(str(uuid.uuid4()), str(uuid.uuid4()))

    @pytest.mark.asyncio
    async def test_forbidden_error_propagates(self) -> None:
        with (
            patch(
                "app.tasks.auto_grouping._get_class_id_for_grade",
                new=AsyncMock(side_effect=ForbiddenError("Access denied.")),
            ),
            pytest.raises(ForbiddenError),
        ):
            await _run_compute_class_groups(str(uuid.uuid4()), str(uuid.uuid4()))


# ---------------------------------------------------------------------------
# Tests — compute_class_groups Celery task (eager execution)
# ---------------------------------------------------------------------------


class TestComputeClassGroupsTask:
    def test_happy_path_succeeds(self) -> None:
        grade_id = str(uuid.uuid4())
        teacher_id = str(uuid.uuid4())

        with patch("app.tasks.auto_grouping.asyncio.run", return_value=None) as mock_run:
            result = compute_class_groups(grade_id, teacher_id)
            assert result is None
            mock_run.assert_called_once()

    def test_not_found_does_not_retry(self) -> None:
        """NotFoundError is swallowed — task succeeds without retry."""
        grade_id = str(uuid.uuid4())
        teacher_id = str(uuid.uuid4())

        with patch(
            "app.tasks.auto_grouping._run_compute_class_groups",
            new=AsyncMock(side_effect=NotFoundError("Grade not found.")),
        ):
            result = compute_class_groups.apply(args=[grade_id, teacher_id])

        assert result.successful(), "NotFoundError should be swallowed, task should succeed"

    def test_forbidden_does_not_retry(self) -> None:
        """ForbiddenError is swallowed — task succeeds without retry."""
        grade_id = str(uuid.uuid4())
        teacher_id = str(uuid.uuid4())

        with patch(
            "app.tasks.auto_grouping._run_compute_class_groups",
            new=AsyncMock(side_effect=ForbiddenError("Access denied.")),
        ):
            result = compute_class_groups.apply(args=[grade_id, teacher_id])

        assert result.successful(), "ForbiddenError should be swallowed, task should succeed"

    def test_transient_error_triggers_retry_then_fails(self) -> None:
        """A RuntimeError causes retries; after exhaustion the task fails."""
        grade_id = str(uuid.uuid4())
        teacher_id = str(uuid.uuid4())

        with patch(
            "app.tasks.auto_grouping._run_compute_class_groups",
            new=AsyncMock(side_effect=RuntimeError("DB unavailable")),
        ):
            result = compute_class_groups.apply(args=[grade_id, teacher_id])

        assert result.failed(), "Task should fail after exhausting retries"

    def test_idempotent_on_second_call(self) -> None:
        """Calling the task twice with the same arguments both succeed."""
        grade_id = str(uuid.uuid4())
        teacher_id = str(uuid.uuid4())

        with patch("app.tasks.auto_grouping.asyncio.run", return_value=None):
            r1 = compute_class_groups(grade_id, teacher_id)
            r2 = compute_class_groups(grade_id, teacher_id)

        assert r1 is None
        assert r2 is None


# ---------------------------------------------------------------------------
# Tests — lock_grade triggers compute_class_groups
# ---------------------------------------------------------------------------


class TestLockGradeTriggersAutoGroupingTask:
    """Verify that lock_grade enqueues the compute_class_groups task."""

    @pytest.mark.asyncio
    async def test_auto_grouping_task_enqueued_on_first_lock(self) -> None:
        """compute_class_groups.delay is called once when a grade is first locked."""
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

        auto_grouping_delay_calls: list[tuple[str, str]] = []
        skill_profile_task_mock = MagicMock()
        skill_profile_task_mock.delay = MagicMock()

        auto_grouping_task_mock = MagicMock()
        auto_grouping_task_mock.delay = MagicMock(
            side_effect=lambda gid, tid: auto_grouping_delay_calls.append((gid, tid))
        )

        with (
            patch.dict(
                "sys.modules",
                {
                    "app.tasks.skill_profile": MagicMock(
                        update_skill_profile=skill_profile_task_mock
                    ),
                    "app.tasks.auto_grouping": MagicMock(
                        compute_class_groups=auto_grouping_task_mock
                    ),
                },
            ),
        ):
            await lock_grade(db=db, grade_id=grade_id, teacher_id=teacher_id)

        assert len(auto_grouping_delay_calls) == 1, (
            "compute_class_groups.delay should be called exactly once"
        )
        assert auto_grouping_delay_calls[0] == (str(grade_id), str(teacher_id))

    @pytest.mark.asyncio
    async def test_auto_grouping_task_not_enqueued_for_already_locked_grade(self) -> None:
        """Already-locked grade is a no-op — compute_class_groups is NOT enqueued."""
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
        grade_mock.is_locked = True
        grade_mock.locked_at = datetime.now(UTC)
        grade_mock.overall_confidence = ConfidenceLevel.high
        grade_mock.created_at = datetime.now(UTC)

        # UPDATE ... WHERE is_locked=FALSE returns None → grade was already locked.
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

        auto_grouping_delay_calls: list[tuple[str, str]] = []
        auto_grouping_task_mock = MagicMock()
        auto_grouping_task_mock.delay = MagicMock(
            side_effect=lambda gid, tid: auto_grouping_delay_calls.append((gid, tid))
        )

        with (
            patch.dict(
                "sys.modules",
                {
                    "app.tasks.skill_profile": MagicMock(update_skill_profile=MagicMock()),
                    "app.tasks.auto_grouping": MagicMock(
                        compute_class_groups=auto_grouping_task_mock
                    ),
                },
            ),
        ):
            await lock_grade(db=db, grade_id=grade_id, teacher_id=teacher_id)

        assert len(auto_grouping_delay_calls) == 0, (
            "compute_class_groups.delay must not be called for an already-locked grade"
        )
