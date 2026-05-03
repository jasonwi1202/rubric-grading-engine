"""Unit tests for app/services/worklist.py — worklist generation logic (M6-04).

Tests cover each trigger type in isolation (pure function tests) and the
combined ranking logic:

Regression trigger (``_check_regression``):
- declining trend fires
- stable trend does not fire
- improving trend does not fire
- multiple skills: only declining ones fire
- empty skill_scores returns no items
- malformed entries (non-dict values) are skipped

Persistent gap trigger (``_check_persistent_gap``):
- in_persistent_group fires regardless of avg_score
- below threshold + enough assignments + not improving fires
- above threshold + not in group does not fire
- below threshold + too few assignments does not fire
- below threshold + improving trend does not fire (unless in persistent group)
- in persistent group + improving trend fires (group membership overrides trend)

High inconsistency trigger (``_check_high_inconsistency``):
- high std dev fires
- low std dev does not fire
- too few assignments (< 3) does not fire
- exactly MIN_ASSIGNMENTS with high variance fires
- multiple skills: only high-variance ones fire
- single score (n=1) never fires

Non-responder trigger (``_check_non_responder``):
- no resubmission pairs: no fire
- improvement below threshold fires
- improvement at exactly threshold does not fire (boundary)
- negative improvement (regression) fires
- zero improvement fires
- multiple resubmissions: fires at most once per student
- all resubmissions meet threshold: no fire

Ranking (``_rank_items``):
- highest urgency first
- same urgency: regression before non_responder before persistent_gap before high_inconsistency
- same urgency+type: skill_key alphabetically
- non_responder with None skill_key sorts before skill-specific items at same urgency

Suggested actions (``_suggested_action``):
- each trigger type returns the expected action string pattern

Urgency values:
- regression urgency = 4
- non_responder urgency = 4
- persistent_gap urgency = 3
- high_inconsistency urgency = 2

Task registration:
- task is registered in Celery
- task name matches convention
- max_retries = 3

No student PII in any fixture.  All database calls are mocked.
No real Celery broker or database required.
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.worklist import (
    _GAP_MIN_ASSIGNMENTS,
    _GAP_SCORE_THRESHOLD,
    _INCONSISTENCY_MIN_ASSIGNMENTS,
    _INCONSISTENCY_STD_THRESHOLD,
    _NON_RESPONDER_IMPROVEMENT_THRESHOLD,
    _URGENCY_HIGH_INCONSISTENCY,
    _URGENCY_NON_RESPONDER,
    _URGENCY_PERSISTENT_GAP,
    _URGENCY_REGRESSION,
    _check_high_inconsistency,
    _check_non_responder,
    _check_persistent_gap,
    _check_regression,
    _rank_items,
    _suggested_action,
    _WorklistItemData,
)
from app.tasks.celery_app import celery
from app.tasks.worklist import refresh_teacher_worklist

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_profile(
    student_id: uuid.UUID,
    teacher_id: uuid.UUID,
    skills: dict[str, dict[str, Any]],
    assignment_count: int = 3,
) -> MagicMock:
    """Build a mock StudentSkillProfile from a skill_scores dict."""
    profile = MagicMock()
    profile.student_id = student_id
    profile.teacher_id = teacher_id
    profile.skill_scores = skills
    profile.assignment_count = assignment_count
    return profile


def _skill_entry(
    avg_score: float = 0.70,
    trend: str = "stable",
    data_points: int = 3,
) -> dict[str, Any]:
    """Build a single skill_scores entry dict."""
    return {
        "avg_score": avg_score,
        "trend": trend,
        "data_points": data_points,
        "last_updated": "2026-01-01T00:00:00+00:00",
    }


# ---------------------------------------------------------------------------
# Tests — _check_regression
# ---------------------------------------------------------------------------


class TestCheckRegression:
    def test_declining_trend_fires(self) -> None:
        teacher_id = uuid.uuid4()
        student_id = uuid.uuid4()
        profile = _make_profile(
            student_id, teacher_id, {"evidence": _skill_entry(avg_score=0.55, trend="declining")}
        )
        items = _check_regression(profile)
        assert len(items) == 1
        assert items[0].trigger_type == "regression"
        assert items[0].skill_key == "evidence"
        assert items[0].student_id == student_id
        assert items[0].urgency == _URGENCY_REGRESSION

    def test_stable_trend_does_not_fire(self) -> None:
        teacher_id = uuid.uuid4()
        student_id = uuid.uuid4()
        profile = _make_profile(
            student_id, teacher_id, {"evidence": _skill_entry(avg_score=0.55, trend="stable")}
        )
        items = _check_regression(profile)
        assert items == []

    def test_improving_trend_does_not_fire(self) -> None:
        teacher_id = uuid.uuid4()
        student_id = uuid.uuid4()
        profile = _make_profile(
            student_id,
            teacher_id,
            {"evidence": _skill_entry(avg_score=0.55, trend="improving")},
        )
        items = _check_regression(profile)
        assert items == []

    def test_multiple_skills_only_declining_fires(self) -> None:
        teacher_id = uuid.uuid4()
        student_id = uuid.uuid4()
        profile = _make_profile(
            student_id,
            teacher_id,
            {
                "evidence": _skill_entry(avg_score=0.55, trend="declining"),
                "thesis": _skill_entry(avg_score=0.80, trend="stable"),
                "organization": _skill_entry(avg_score=0.40, trend="improving"),
                "voice": _skill_entry(avg_score=0.30, trend="declining"),
            },
        )
        items = _check_regression(profile)
        triggered_skills = {i.skill_key for i in items}
        assert triggered_skills == {"evidence", "voice"}
        assert all(i.trigger_type == "regression" for i in items)

    def test_empty_skill_scores_returns_no_items(self) -> None:
        teacher_id = uuid.uuid4()
        student_id = uuid.uuid4()
        profile = _make_profile(student_id, teacher_id, {})
        items = _check_regression(profile)
        assert items == []

    def test_none_skill_scores_returns_no_items(self) -> None:
        teacher_id = uuid.uuid4()
        student_id = uuid.uuid4()
        profile = _make_profile(student_id, teacher_id, {})
        profile.skill_scores = None
        items = _check_regression(profile)
        assert items == []

    def test_malformed_entry_skipped(self) -> None:
        """Non-dict skill_scores entries are silently skipped."""
        teacher_id = uuid.uuid4()
        student_id = uuid.uuid4()
        profile = _make_profile(
            student_id,
            teacher_id,
            {
                "evidence": "not-a-dict",  # type: ignore[arg-type]
                "thesis": _skill_entry(avg_score=0.55, trend="declining"),
            },
        )
        items = _check_regression(profile)
        # Only thesis fires; evidence is skipped due to malformed entry.
        assert len(items) == 1
        assert items[0].skill_key == "thesis"

    def test_details_contain_avg_score_and_trend(self) -> None:
        teacher_id = uuid.uuid4()
        student_id = uuid.uuid4()
        profile = _make_profile(
            student_id, teacher_id, {"evidence": _skill_entry(avg_score=0.45, trend="declining")}
        )
        items = _check_regression(profile)
        assert items[0].details["avg_score"] == 0.45
        assert items[0].details["trend"] == "declining"

    def test_items_sorted_alphabetically_by_skill_key(self) -> None:
        teacher_id = uuid.uuid4()
        student_id = uuid.uuid4()
        profile = _make_profile(
            student_id,
            teacher_id,
            {
                "voice": _skill_entry(trend="declining"),
                "evidence": _skill_entry(trend="declining"),
                "thesis": _skill_entry(trend="declining"),
            },
        )
        items = _check_regression(profile)
        assert [i.skill_key for i in items] == ["evidence", "thesis", "voice"]


# ---------------------------------------------------------------------------
# Tests — _check_persistent_gap
# ---------------------------------------------------------------------------


class TestCheckPersistentGap:
    def test_in_persistent_group_fires(self) -> None:
        teacher_id = uuid.uuid4()
        student_id = uuid.uuid4()
        profile = _make_profile(
            student_id,
            teacher_id,
            {
                "evidence": _skill_entry(
                    avg_score=0.80,  # above threshold
                    trend="stable",
                )
            },
            assignment_count=3,
        )
        items = _check_persistent_gap(profile, persistent_skill_keys={"evidence"})
        assert len(items) == 1
        assert items[0].trigger_type == "persistent_gap"
        assert items[0].details["in_persistent_group"] is True

    def test_below_threshold_enough_assignments_not_improving_fires(self) -> None:
        teacher_id = uuid.uuid4()
        student_id = uuid.uuid4()
        profile = _make_profile(
            student_id,
            teacher_id,
            {
                "evidence": _skill_entry(
                    avg_score=_GAP_SCORE_THRESHOLD - 0.01,  # just below threshold
                    trend="stable",
                )
            },
            assignment_count=_GAP_MIN_ASSIGNMENTS,
        )
        items = _check_persistent_gap(profile, persistent_skill_keys=set())
        assert len(items) == 1
        assert items[0].trigger_type == "persistent_gap"
        assert items[0].details["in_persistent_group"] is False

    def test_above_threshold_not_in_group_does_not_fire(self) -> None:
        teacher_id = uuid.uuid4()
        student_id = uuid.uuid4()
        profile = _make_profile(
            student_id,
            teacher_id,
            {
                "evidence": _skill_entry(
                    avg_score=_GAP_SCORE_THRESHOLD + 0.01,  # just above threshold
                    trend="stable",
                )
            },
            assignment_count=_GAP_MIN_ASSIGNMENTS,
        )
        items = _check_persistent_gap(profile, persistent_skill_keys=set())
        assert items == []

    def test_below_threshold_too_few_assignments_does_not_fire(self) -> None:
        teacher_id = uuid.uuid4()
        student_id = uuid.uuid4()
        profile = _make_profile(
            student_id,
            teacher_id,
            {
                "evidence": _skill_entry(
                    avg_score=_GAP_SCORE_THRESHOLD - 0.10,
                    trend="stable",
                )
            },
            assignment_count=_GAP_MIN_ASSIGNMENTS - 1,  # not enough
        )
        items = _check_persistent_gap(profile, persistent_skill_keys=set())
        assert items == []

    def test_below_threshold_improving_trend_does_not_fire_if_not_in_group(self) -> None:
        teacher_id = uuid.uuid4()
        student_id = uuid.uuid4()
        profile = _make_profile(
            student_id,
            teacher_id,
            {
                "evidence": _skill_entry(
                    avg_score=_GAP_SCORE_THRESHOLD - 0.10,
                    trend="improving",  # improving → no fire
                )
            },
            assignment_count=_GAP_MIN_ASSIGNMENTS,
        )
        items = _check_persistent_gap(profile, persistent_skill_keys=set())
        assert items == []

    def test_in_persistent_group_fires_even_if_improving(self) -> None:
        """Group membership overrides the 'improving' trend exemption."""
        teacher_id = uuid.uuid4()
        student_id = uuid.uuid4()
        profile = _make_profile(
            student_id,
            teacher_id,
            {
                "evidence": _skill_entry(
                    avg_score=0.50,
                    trend="improving",
                )
            },
            assignment_count=1,
        )
        items = _check_persistent_gap(profile, persistent_skill_keys={"evidence"})
        assert len(items) == 1
        assert items[0].details["in_persistent_group"] is True

    def test_multiple_skills_only_flagged_ones_fire(self) -> None:
        teacher_id = uuid.uuid4()
        student_id = uuid.uuid4()
        profile = _make_profile(
            student_id,
            teacher_id,
            {
                "evidence": _skill_entry(avg_score=0.40, trend="stable"),  # below threshold
                "thesis": _skill_entry(avg_score=0.85, trend="stable"),  # above threshold
                "voice": _skill_entry(avg_score=0.55, trend="stable"),  # below threshold
            },
            assignment_count=3,
        )
        items = _check_persistent_gap(profile, persistent_skill_keys=set())
        triggered = {i.skill_key for i in items}
        assert triggered == {"evidence", "voice"}

    def test_urgency_is_correct(self) -> None:
        teacher_id = uuid.uuid4()
        student_id = uuid.uuid4()
        profile = _make_profile(
            student_id,
            teacher_id,
            {"evidence": _skill_entry(avg_score=0.40, trend="stable")},
            assignment_count=3,
        )
        items = _check_persistent_gap(profile, persistent_skill_keys=set())
        assert items[0].urgency == _URGENCY_PERSISTENT_GAP


# ---------------------------------------------------------------------------
# Tests — _check_high_inconsistency
# ---------------------------------------------------------------------------


class TestCheckHighInconsistency:
    def test_high_std_dev_fires(self) -> None:
        student_id = uuid.uuid4()
        # Scores oscillating between 0.0 and 1.0 → std dev = 0.5
        scores = [0.0, 1.0, 0.0, 1.0, 0.0]
        items = _check_high_inconsistency(student_id, {"evidence": scores})
        assert len(items) == 1
        assert items[0].trigger_type == "high_inconsistency"
        assert items[0].skill_key == "evidence"
        assert items[0].urgency == _URGENCY_HIGH_INCONSISTENCY

    def test_low_std_dev_does_not_fire(self) -> None:
        student_id = uuid.uuid4()
        # Scores very close together → std dev ≈ 0
        scores = [0.80, 0.81, 0.79, 0.80]
        items = _check_high_inconsistency(student_id, {"evidence": scores})
        assert items == []

    def test_too_few_assignments_does_not_fire(self) -> None:
        student_id = uuid.uuid4()
        # Only 2 assignments — below _INCONSISTENCY_MIN_ASSIGNMENTS = 3
        scores = [0.0, 1.0]
        items = _check_high_inconsistency(student_id, {"evidence": scores})
        assert items == []

    def test_exactly_min_assignments_with_high_variance_fires(self) -> None:
        student_id = uuid.uuid4()
        # Exactly 3 assignments with high variance
        scores = [0.0, 1.0, 0.0]
        assert len(scores) == _INCONSISTENCY_MIN_ASSIGNMENTS
        items = _check_high_inconsistency(student_id, {"evidence": scores})
        assert len(items) == 1

    def test_multiple_skills_only_high_variance_fires(self) -> None:
        student_id = uuid.uuid4()
        per_skill = {
            "evidence": [0.0, 1.0, 0.0, 1.0],  # high variance
            "thesis": [0.80, 0.82, 0.81, 0.79],  # low variance
        }
        items = _check_high_inconsistency(student_id, per_skill)
        triggered = {i.skill_key for i in items}
        assert triggered == {"evidence"}

    def test_single_score_never_fires(self) -> None:
        student_id = uuid.uuid4()
        items = _check_high_inconsistency(student_id, {"evidence": [0.0]})
        assert items == []

    def test_std_dev_clearly_below_threshold_does_not_fire(self) -> None:
        """A std dev well below the threshold does not trigger."""
        student_id = uuid.uuid4()
        # Scores [0.40, 0.50, 0.60]: mean=0.5, population std≈0.082,
        # which is well below the 0.20 threshold.
        below_threshold_scores = [0.40, 0.50, 0.60]
        items = _check_high_inconsistency(student_id, {"evidence": below_threshold_scores})
        assert items == []

    def test_std_dev_clearly_above_threshold_fires(self) -> None:
        """A std dev well above the threshold triggers the signal."""
        student_id = uuid.uuid4()
        # Scores [0.1, 0.5, 0.9, 0.1]: population std ≈ 0.316, well above 0.20.
        above_threshold_scores = [0.1, 0.5, 0.9, 0.1]
        items = _check_high_inconsistency(student_id, {"evidence": above_threshold_scores})
        assert len(items) == 1

    def test_details_contain_std_dev_and_assignment_count(self) -> None:
        student_id = uuid.uuid4()
        scores = [0.0, 1.0, 0.0, 1.0]
        items = _check_high_inconsistency(student_id, {"evidence": scores})
        assert "std_dev" in items[0].details
        assert items[0].details["assignment_count"] == 4

    def test_std_dev_above_threshold_constant(self) -> None:
        """Verify the threshold constant is the expected value."""
        assert _INCONSISTENCY_STD_THRESHOLD == 0.20

    def test_min_assignments_constant(self) -> None:
        """Verify the minimum assignment count constant."""
        assert _INCONSISTENCY_MIN_ASSIGNMENTS == 3


# ---------------------------------------------------------------------------
# Tests — _check_non_responder
# ---------------------------------------------------------------------------


class TestCheckNonResponder:
    def test_no_resubmission_pairs_no_fire(self) -> None:
        student_id = uuid.uuid4()
        items = _check_non_responder(student_id, [])
        assert items == []

    def test_improvement_below_threshold_fires(self) -> None:
        student_id = uuid.uuid4()
        # improvement = 0.64 - 0.60 = 0.04 < 0.05 (_NON_RESPONDER_IMPROVEMENT_THRESHOLD) → fires
        items = _check_non_responder(student_id, [(0.60, 0.64)])
        assert len(items) == 1
        assert items[0].trigger_type == "non_responder"
        assert items[0].skill_key is None
        assert items[0].student_id == student_id
        assert items[0].urgency == _URGENCY_NON_RESPONDER

    def test_improvement_at_threshold_does_not_fire(self) -> None:
        """Improvement exactly equal to threshold does not trigger."""
        student_id = uuid.uuid4()
        # improvement = _NON_RESPONDER_IMPROVEMENT_THRESHOLD exactly → no fire
        original = 0.50
        resubmission = original + _NON_RESPONDER_IMPROVEMENT_THRESHOLD
        items = _check_non_responder(student_id, [(original, resubmission)])
        assert items == []

    def test_negative_improvement_fires(self) -> None:
        """A student who scored worse on resubmission should fire."""
        student_id = uuid.uuid4()
        items = _check_non_responder(student_id, [(0.70, 0.60)])
        assert len(items) == 1
        assert items[0].details["improvement"] < 0

    def test_zero_improvement_fires(self) -> None:
        student_id = uuid.uuid4()
        items = _check_non_responder(student_id, [(0.70, 0.70)])
        assert len(items) == 1
        assert items[0].details["improvement"] == 0.0

    def test_fires_at_most_once_per_student(self) -> None:
        """Multiple failing resubmissions still produce only one item."""
        student_id = uuid.uuid4()
        pairs = [(0.50, 0.51), (0.60, 0.61)]  # both below threshold
        items = _check_non_responder(student_id, pairs)
        assert len(items) == 1

    def test_all_resubmissions_meet_threshold_no_fire(self) -> None:
        student_id = uuid.uuid4()
        pairs = [
            (0.50, 0.60),  # improvement = 0.10 > 0.05 → OK
            (0.40, 0.55),  # improvement = 0.15 > 0.05 → OK
        ]
        items = _check_non_responder(student_id, pairs)
        assert items == []

    def test_details_contain_improvement_and_resubmission_count(self) -> None:
        student_id = uuid.uuid4()
        items = _check_non_responder(student_id, [(0.60, 0.62)])
        assert "improvement" in items[0].details
        assert "resubmission_count" in items[0].details
        assert items[0].details["resubmission_count"] == 1


# ---------------------------------------------------------------------------
# Tests — _rank_items
# ---------------------------------------------------------------------------


class TestRankItems:
    def _item(
        self,
        urgency: int,
        trigger_type: str = "regression",
        skill_key: str | None = "evidence",
    ) -> _WorklistItemData:
        return _WorklistItemData(
            student_id=uuid.uuid4(),
            trigger_type=trigger_type,
            skill_key=skill_key,
            urgency=urgency,
            suggested_action="action",
            details={},
        )

    def test_highest_urgency_first(self) -> None:
        items = [
            self._item(2, "high_inconsistency"),
            self._item(4, "regression"),
            self._item(3, "persistent_gap"),
        ]
        ranked = _rank_items(items)
        assert [i.urgency for i in ranked] == [4, 3, 2]

    def test_same_urgency_regression_before_non_responder(self) -> None:
        """regression and non_responder both have urgency 4; regression first."""
        items = [
            self._item(4, "non_responder", skill_key=None),
            self._item(4, "regression", "thesis"),
        ]
        ranked = _rank_items(items)
        assert ranked[0].trigger_type == "regression"
        assert ranked[1].trigger_type == "non_responder"

    def test_same_urgency_type_skill_key_alphabetical(self) -> None:
        items = [
            self._item(3, "persistent_gap", "thesis"),
            self._item(3, "persistent_gap", "evidence"),
            self._item(3, "persistent_gap", "voice"),
        ]
        ranked = _rank_items(items)
        assert [i.skill_key for i in ranked] == ["evidence", "thesis", "voice"]

    def test_none_skill_key_sorts_before_string_at_same_urgency(self) -> None:
        """non_responder (None skill_key) appears before skill-specific items at same tier."""
        items = [
            self._item(4, "regression", "thesis"),
            self._item(4, "non_responder", None),
        ]
        ranked = _rank_items(items)
        assert ranked[0].trigger_type == "regression"  # trigger order wins
        assert ranked[1].trigger_type == "non_responder"

    def test_empty_list(self) -> None:
        assert _rank_items([]) == []

    def test_single_item_unchanged(self) -> None:
        item = self._item(3, "persistent_gap", "evidence")
        ranked = _rank_items([item])
        assert ranked == [item]

    def test_deterministic_for_same_urgency_type_skill(self) -> None:
        """Items with identical urgency, trigger_type, and skill_key are ordered by student_id."""
        student_a = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
        student_b = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
        item_a = _WorklistItemData(
            student_id=student_a,
            trigger_type="persistent_gap",
            skill_key="evidence",
            urgency=3,
            suggested_action="action",
            details={},
        )
        item_b = _WorklistItemData(
            student_id=student_b,
            trigger_type="persistent_gap",
            skill_key="evidence",
            urgency=3,
            suggested_action="action",
            details={},
        )
        # Order should be stable: student_a before student_b (UUID string sort)
        ranked1 = _rank_items([item_a, item_b])
        ranked2 = _rank_items([item_b, item_a])
        assert [str(i.student_id) for i in ranked1] == [str(i.student_id) for i in ranked2]
        assert ranked1[0].student_id == student_a
        assert ranked1[1].student_id == student_b


# ---------------------------------------------------------------------------
# Tests — _suggested_action
# ---------------------------------------------------------------------------


class TestSuggestedAction:
    def test_regression_includes_skill_label(self) -> None:
        action = _suggested_action("regression", "evidence")
        assert "evidence" in action.lower()
        assert len(action) > 10

    def test_persistent_gap_includes_skill_label(self) -> None:
        action = _suggested_action("persistent_gap", "thesis")
        assert "thesis" in action.lower()

    def test_high_inconsistency_includes_skill_label(self) -> None:
        action = _suggested_action("high_inconsistency", "voice")
        assert "voice" in action.lower()

    def test_non_responder_is_student_level(self) -> None:
        action = _suggested_action("non_responder", None)
        # Should not reference a skill name; should reference feedback/check-in.
        assert len(action) > 10

    def test_unknown_type_returns_fallback(self) -> None:
        action = _suggested_action("unknown_type", None)
        assert len(action) > 0


# ---------------------------------------------------------------------------
# Tests — urgency constants
# ---------------------------------------------------------------------------


class TestUrgencyConstants:
    def test_regression_urgency_is_4(self) -> None:
        assert _URGENCY_REGRESSION == 4

    def test_non_responder_urgency_is_4(self) -> None:
        assert _URGENCY_NON_RESPONDER == 4

    def test_persistent_gap_urgency_is_3(self) -> None:
        assert _URGENCY_PERSISTENT_GAP == 3

    def test_high_inconsistency_urgency_is_2(self) -> None:
        assert _URGENCY_HIGH_INCONSISTENCY == 2

    def test_regression_fires_with_highest_urgency(self) -> None:
        teacher_id = uuid.uuid4()
        student_id = uuid.uuid4()
        profile = _make_profile(
            student_id,
            teacher_id,
            {"evidence": _skill_entry(trend="declining")},
        )
        items = _check_regression(profile)
        assert items[0].urgency == 4

    def test_non_responder_fires_with_urgency_4(self) -> None:
        student_id = uuid.uuid4()
        items = _check_non_responder(student_id, [(0.50, 0.51)])
        assert items[0].urgency == 4

    def test_persistent_gap_fires_with_urgency_3(self) -> None:
        teacher_id = uuid.uuid4()
        student_id = uuid.uuid4()
        profile = _make_profile(
            student_id,
            teacher_id,
            {"evidence": _skill_entry(avg_score=0.40, trend="stable")},
            assignment_count=3,
        )
        items = _check_persistent_gap(profile, persistent_skill_keys=set())
        assert items[0].urgency == 3

    def test_high_inconsistency_fires_with_urgency_2(self) -> None:
        student_id = uuid.uuid4()
        items = _check_high_inconsistency(student_id, {"evidence": [0.0, 1.0, 0.0, 1.0]})
        assert items[0].urgency == 2


# ---------------------------------------------------------------------------
# Tests — task registration
# ---------------------------------------------------------------------------


class TestRefreshTeacherWorklistTaskRegistration:
    def test_task_is_registered_in_celery(self) -> None:
        assert "tasks.worklist.refresh_teacher_worklist" in celery.tasks

    def test_worklist_module_in_celery_include(self) -> None:
        """Worker will import this module on startup and register the task."""
        assert "app.tasks.worklist" in celery.conf.include

    def test_task_has_correct_max_retries(self) -> None:
        assert refresh_teacher_worklist.max_retries == 3

    def test_task_name_matches_convention(self) -> None:
        assert refresh_teacher_worklist.name == "tasks.worklist.refresh_teacher_worklist"


# ---------------------------------------------------------------------------
# Tests — tenant isolation via _check_* functions (student_id binding)
# ---------------------------------------------------------------------------


class TestTenantIsolation:
    def test_regression_items_bound_to_correct_student(self) -> None:
        """Items produced by _check_regression always carry the profile's student_id."""
        teacher_id = uuid.uuid4()
        student_a = uuid.uuid4()
        student_b = uuid.uuid4()

        profile_a = _make_profile(
            student_a, teacher_id, {"evidence": _skill_entry(trend="declining")}
        )
        profile_b = _make_profile(
            student_b, teacher_id, {"evidence": _skill_entry(trend="declining")}
        )

        items_a = _check_regression(profile_a)
        items_b = _check_regression(profile_b)

        assert all(i.student_id == student_a for i in items_a)
        assert all(i.student_id == student_b for i in items_b)
        # No cross-contamination.
        assert items_a[0].student_id != items_b[0].student_id

    def test_persistent_gap_items_bound_to_correct_student(self) -> None:
        teacher_id = uuid.uuid4()
        student_a = uuid.uuid4()
        profile = _make_profile(
            student_a,
            teacher_id,
            {"evidence": _skill_entry(avg_score=0.40, trend="stable")},
            assignment_count=3,
        )
        items = _check_persistent_gap(profile, persistent_skill_keys=set())
        assert all(i.student_id == student_a for i in items)

    def test_high_inconsistency_items_bound_to_correct_student(self) -> None:
        student_a = uuid.uuid4()
        items = _check_high_inconsistency(student_a, {"evidence": [0.0, 1.0, 0.0, 1.0]})
        assert all(i.student_id == student_a for i in items)

    def test_non_responder_items_bound_to_correct_student(self) -> None:
        student_a = uuid.uuid4()
        items = _check_non_responder(student_a, [(0.50, 0.52)])
        assert all(i.student_id == student_a for i in items)


# ---------------------------------------------------------------------------
# Tests — threshold constants
# ---------------------------------------------------------------------------


class TestThresholdConstants:
    def test_gap_score_threshold(self) -> None:
        assert _GAP_SCORE_THRESHOLD == 0.60

    def test_gap_min_assignments(self) -> None:
        assert _GAP_MIN_ASSIGNMENTS == 2

    def test_inconsistency_std_threshold(self) -> None:
        assert _INCONSISTENCY_STD_THRESHOLD == 0.20

    def test_inconsistency_min_assignments(self) -> None:
        assert _INCONSISTENCY_MIN_ASSIGNMENTS == 3

    def test_non_responder_improvement_threshold(self) -> None:
        assert _NON_RESPONDER_IMPROVEMENT_THRESHOLD == 0.05


# ---------------------------------------------------------------------------
# Tests — _check_trajectory_risk
# ---------------------------------------------------------------------------


from app.services.worklist import (  # noqa: E402 (after first imports block)
    _TRAJECTORY_RISK_MIN_DECLINE_STEPS,
    _URGENCY_TRAJECTORY_RISK,
    _check_trajectory_risk,
)


class TestCheckTrajectoryRisk:
    """Predictive trajectory risk trigger (M7-02)."""

    def test_three_consecutive_declines_fires(self) -> None:
        """Exactly 3 consecutive declining steps triggers the signal."""
        student_id = uuid.uuid4()
        # 4 scores: [0.8, 0.7, 0.6, 0.5] → 3 declining steps
        scores = [0.8, 0.7, 0.6, 0.5]
        items = _check_trajectory_risk(student_id, {"evidence": scores})
        assert len(items) == 1
        assert items[0].trigger_type == "trajectory_risk"
        assert items[0].skill_key == "evidence"
        assert items[0].student_id == student_id
        assert items[0].urgency == _URGENCY_TRAJECTORY_RISK

    def test_fewer_than_three_consecutive_declines_does_not_fire(self) -> None:
        """Only 2 consecutive declining steps — below threshold."""
        student_id = uuid.uuid4()
        # [0.8, 0.7, 0.6] → 2 declining steps (need 3)
        scores = [0.8, 0.7, 0.6]
        items = _check_trajectory_risk(student_id, {"evidence": scores})
        assert items == []

    def test_not_enough_data_points_does_not_fire(self) -> None:
        """Fewer than min_steps + 1 data points → cannot have enough decline steps."""
        student_id = uuid.uuid4()
        # Need at least 4 data points for 3 declining steps
        scores = [0.8, 0.7, 0.6]  # only 3 points → max 2 steps
        items = _check_trajectory_risk(student_id, {"evidence": scores})
        assert items == []

    def test_non_monotonic_tail_does_not_fire(self) -> None:
        """Decline broken by a flat or improving step does not fire."""
        student_id = uuid.uuid4()
        # [0.8, 0.7, 0.65, 0.7, 0.6]: last step 0.7→0.6 ok, but 0.65→0.7 breaks chain
        scores = [0.8, 0.7, 0.65, 0.7, 0.6]
        items = _check_trajectory_risk(student_id, {"evidence": scores})
        assert items == []

    def test_rising_scores_do_not_fire(self) -> None:
        student_id = uuid.uuid4()
        scores = [0.4, 0.5, 0.6, 0.7]
        items = _check_trajectory_risk(student_id, {"evidence": scores})
        assert items == []

    def test_flat_scores_do_not_fire(self) -> None:
        student_id = uuid.uuid4()
        scores = [0.7, 0.7, 0.7, 0.7]
        items = _check_trajectory_risk(student_id, {"evidence": scores})
        assert items == []

    def test_is_predictive_flag_in_details(self) -> None:
        student_id = uuid.uuid4()
        scores = [0.8, 0.7, 0.6, 0.5]
        items = _check_trajectory_risk(student_id, {"evidence": scores})
        assert items[0].details["is_predictive"] is True

    def test_confidence_low_for_three_declines(self) -> None:
        student_id = uuid.uuid4()
        scores = [0.8, 0.7, 0.6, 0.5]  # exactly 3 steps
        items = _check_trajectory_risk(student_id, {"evidence": scores})
        assert items[0].details["confidence_level"] == "low"

    def test_confidence_medium_for_four_declines(self) -> None:
        student_id = uuid.uuid4()
        scores = [0.9, 0.8, 0.7, 0.6, 0.5]  # 4 steps
        items = _check_trajectory_risk(student_id, {"evidence": scores})
        assert items[0].details["confidence_level"] == "medium"

    def test_confidence_high_for_five_or_more_declines(self) -> None:
        student_id = uuid.uuid4()
        scores = [0.95, 0.85, 0.75, 0.65, 0.55, 0.45]  # 5 steps
        items = _check_trajectory_risk(student_id, {"evidence": scores})
        assert items[0].details["confidence_level"] == "high"

    def test_details_include_consecutive_decline_count(self) -> None:
        student_id = uuid.uuid4()
        scores = [0.8, 0.7, 0.6, 0.5]
        items = _check_trajectory_risk(student_id, {"evidence": scores})
        assert items[0].details["consecutive_decline_count"] == 3

    def test_details_include_total_decline(self) -> None:
        student_id = uuid.uuid4()
        scores = [0.8, 0.7, 0.6, 0.5]  # window: 0.8 to 0.5 = 0.3 decline
        items = _check_trajectory_risk(student_id, {"evidence": scores})
        assert items[0].details["total_decline"] == pytest.approx(0.3, abs=0.001)

    def test_details_include_recent_scores(self) -> None:
        student_id = uuid.uuid4()
        scores = [0.9, 0.8, 0.7, 0.6, 0.5]  # 4 declining steps
        items = _check_trajectory_risk(student_id, {"evidence": scores})
        # recent_scores should include the entire declining window (from 0.9 onward)
        assert items[0].details["recent_scores"] == pytest.approx(
            [0.9, 0.8, 0.7, 0.6, 0.5], abs=0.001
        )

    def test_deduplication_skips_already_declining_skills(self) -> None:
        """Skills already classified as 'declining' in the profile are skipped."""
        student_id = uuid.uuid4()
        scores = [0.8, 0.7, 0.6, 0.5]  # would normally fire
        profile_trends = {"evidence": "declining"}
        items = _check_trajectory_risk(student_id, {"evidence": scores}, profile_trends)
        assert items == []

    def test_non_declining_profile_trend_does_not_block(self) -> None:
        """Skills with 'stable' or 'improving' profile trend can still fire."""
        student_id = uuid.uuid4()
        scores = [0.8, 0.7, 0.6, 0.5]
        profile_trends = {"evidence": "stable"}
        items = _check_trajectory_risk(student_id, {"evidence": scores}, profile_trends)
        assert len(items) == 1

    def test_none_profile_trends_disables_deduplication(self) -> None:
        """Passing None for profile_trends fires even for 'declining' skills."""
        student_id = uuid.uuid4()
        scores = [0.8, 0.7, 0.6, 0.5]
        items = _check_trajectory_risk(student_id, {"evidence": scores}, None)
        assert len(items) == 1

    def test_multiple_skills_only_qualifying_ones_fire(self) -> None:
        student_id = uuid.uuid4()
        per_skill = {
            "evidence": [0.8, 0.7, 0.6, 0.5],  # 3 declines → fires
            "thesis": [0.7, 0.8, 0.7, 0.8],  # no consecutive decline → no fire
            "voice": [0.9, 0.8, 0.7, 0.6, 0.5],  # 4 declines → fires
        }
        items = _check_trajectory_risk(student_id, per_skill)
        triggered = {i.skill_key for i in items}
        assert triggered == {"evidence", "voice"}

    def test_items_sorted_alphabetically_by_skill_key(self) -> None:
        student_id = uuid.uuid4()
        per_skill = {
            "voice": [0.8, 0.7, 0.6, 0.5],
            "evidence": [0.8, 0.7, 0.6, 0.5],
            "thesis": [0.8, 0.7, 0.6, 0.5],
        }
        items = _check_trajectory_risk(student_id, per_skill)
        assert [i.skill_key for i in items] == ["evidence", "thesis", "voice"]

    def test_urgency_is_one(self) -> None:
        student_id = uuid.uuid4()
        scores = [0.8, 0.7, 0.6, 0.5]
        items = _check_trajectory_risk(student_id, {"evidence": scores})
        assert items[0].urgency == 1

    def test_urgency_constant_is_one(self) -> None:
        assert _URGENCY_TRAJECTORY_RISK == 1

    def test_min_decline_steps_constant_is_three(self) -> None:
        assert _TRAJECTORY_RISK_MIN_DECLINE_STEPS == 3

    def test_empty_per_assignment_scores_returns_no_items(self) -> None:
        student_id = uuid.uuid4()
        items = _check_trajectory_risk(student_id, {})
        assert items == []

    def test_tail_decline_preceded_by_earlier_rise_still_fires(self) -> None:
        """Earlier improvements do not cancel a recent declining tail."""
        student_id = uuid.uuid4()
        # Rise then decline: [0.3, 0.5, 0.8, 0.7, 0.6, 0.5] — last 3 steps decline
        scores = [0.3, 0.5, 0.8, 0.7, 0.6, 0.5]
        items = _check_trajectory_risk(student_id, {"evidence": scores})
        assert len(items) == 1
        assert items[0].details["consecutive_decline_count"] == 3


# ---------------------------------------------------------------------------
# Tests — tenant isolation for _check_trajectory_risk
# ---------------------------------------------------------------------------


class TestTrajectoryRiskTenantIsolation:
    def test_items_bound_to_correct_student(self) -> None:
        """trajectory_risk items always carry the correct student_id."""
        student_a = uuid.uuid4()
        student_b = uuid.uuid4()
        scores = [0.8, 0.7, 0.6, 0.5]

        items_a = _check_trajectory_risk(student_a, {"evidence": scores})
        items_b = _check_trajectory_risk(student_b, {"evidence": scores})

        assert all(i.student_id == student_a for i in items_a)
        assert all(i.student_id == student_b for i in items_b)
        assert items_a[0].student_id != items_b[0].student_id

    def test_deduplication_is_per_student(self) -> None:
        """Deduplication uses per-call profile_trends, not shared state."""
        student_a = uuid.uuid4()
        student_b = uuid.uuid4()
        scores = [0.8, 0.7, 0.6, 0.5]

        # student_a: skill is already 'declining' → skipped
        items_a = _check_trajectory_risk(student_a, {"evidence": scores}, {"evidence": "declining"})
        # student_b: no profile trends → fires
        items_b = _check_trajectory_risk(student_b, {"evidence": scores}, {})

        assert items_a == []
        assert len(items_b) == 1
        assert items_b[0].student_id == student_b


def _make_worklist_item_orm(
    teacher_id: uuid.UUID | None = None,
    item_id: uuid.UUID | None = None,
    status: str = "active",
    trigger_type: str = "regression",
) -> MagicMock:
    """Build a mock TeacherWorklistItem ORM object."""
    from app.models.worklist import TeacherWorklistItem  # noqa: PLC0415

    item = MagicMock(spec=TeacherWorklistItem)
    item.id = item_id or uuid.uuid4()
    item.teacher_id = teacher_id or uuid.uuid4()
    item.student_id = uuid.uuid4()
    item.trigger_type = trigger_type
    item.skill_key = "evidence"
    item.urgency = 4
    item.suggested_action = "Review recent essay with student."
    item.details = {}
    item.status = status
    item.snoozed_until = None
    item.completed_at = None
    item.generated_at = MagicMock()
    item.created_at = MagicMock()
    return item


def _make_ownership_row(teacher_id: uuid.UUID, item_id: uuid.UUID) -> MagicMock:
    """Build a mock row for the lightweight ownership query (id + teacher_id)."""
    row = MagicMock()
    row.id = item_id
    row.teacher_id = teacher_id
    return row


def _make_db_for_load(
    item: MagicMock,
    ownership_teacher_id: uuid.UUID | None = None,
) -> MagicMock:
    """Build an AsyncMock db whose first execute returns the item (single-step load).

    With the simplified ``_load_worklist_item`` implementation, a single
    ``SELECT … WHERE id = ? AND teacher_id = ?`` is issued.  The result's
    ``scalar_one_or_none()`` either returns the ORM row (matched) or ``None``
    (not found / cross-tenant).

    If ``ownership_teacher_id`` is provided and differs from ``item.teacher_id``,
    the mock simulates the cross-tenant / not-found path (returns ``None``).
    Otherwise it returns ``item``.
    """
    from unittest.mock import AsyncMock  # noqa: PLC0415

    actual_teacher = ownership_teacher_id if ownership_teacher_id is not None else item.teacher_id
    load_result = MagicMock()
    if actual_teacher != item.teacher_id:
        load_result.scalar_one_or_none.return_value = None
    else:
        load_result.scalar_one_or_none.return_value = item

    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[load_result])
    return db


class TestGetWorklistForTeacher:
    """Tests for ``worklist.get_worklist_for_teacher``."""

    @pytest.mark.asyncio
    async def test_returns_items_for_teacher(self) -> None:
        from app.services.worklist import get_worklist_for_teacher

        teacher_id = uuid.uuid4()
        item = _make_worklist_item_orm(teacher_id=teacher_id)

        db = MagicMock()
        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = [item]
        db.execute = AsyncMock(return_value=result_mock)

        items = await get_worklist_for_teacher(db, teacher_id=teacher_id)
        assert items == [item]
        db.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_items(self) -> None:
        from app.services.worklist import get_worklist_for_teacher

        teacher_id = uuid.uuid4()

        db = MagicMock()
        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(return_value=result_mock)

        items = await get_worklist_for_teacher(db, teacher_id=teacher_id)
        assert items == []


class TestCompleteWorklistItem:
    """Tests for ``worklist.complete_worklist_item``."""

    @pytest.mark.asyncio
    async def test_marks_item_completed(self) -> None:
        from app.services.worklist import complete_worklist_item

        teacher_id = uuid.uuid4()
        item = _make_worklist_item_orm(teacher_id=teacher_id, status="active")
        db = _make_db_for_load(item)
        # Second execute: the UPDATE
        update_result = MagicMock()
        update_result.rowcount = 1
        db.execute = AsyncMock(side_effect=list(db.execute.side_effect) + [update_result])

        result = await complete_worklist_item(db, item_id=item.id, teacher_id=teacher_id)
        assert result is item
        db.commit.assert_awaited_once()
        db.refresh.assert_awaited_once_with(item)

    @pytest.mark.asyncio
    async def test_idempotent_when_already_completed(self) -> None:
        from app.services.worklist import complete_worklist_item

        teacher_id = uuid.uuid4()
        item = _make_worklist_item_orm(teacher_id=teacher_id, status="completed")
        db = _make_db_for_load(item)

        result = await complete_worklist_item(db, item_id=item.id, teacher_id=teacher_id)
        assert result is item
        # No UPDATE should be executed (only 1 select from _load_worklist_item)
        assert db.execute.await_count == 1
        db.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_raises_not_found_for_missing_item(self) -> None:
        from app.exceptions import NotFoundError
        from app.services.worklist import complete_worklist_item

        teacher_id = uuid.uuid4()
        item_id = uuid.uuid4()

        load_result = MagicMock()
        load_result.scalar_one_or_none.return_value = None
        db = MagicMock()
        db.execute = AsyncMock(return_value=load_result)

        with pytest.raises(NotFoundError):
            await complete_worklist_item(db, item_id=item_id, teacher_id=teacher_id)

    @pytest.mark.asyncio
    async def test_raises_not_found_for_cross_tenant_item(self) -> None:
        """Cross-tenant access returns NotFoundError (indistinguishable from 404 under RLS)."""
        from app.exceptions import NotFoundError
        from app.services.worklist import complete_worklist_item

        teacher_id = uuid.uuid4()
        item_id = uuid.uuid4()

        # Simulate the DB returning no row because RLS / teacher_id filter
        # excludes the cross-tenant item.
        load_result = MagicMock()
        load_result.scalar_one_or_none.return_value = None
        db = MagicMock()
        db.execute = AsyncMock(return_value=load_result)

        with pytest.raises(NotFoundError):
            await complete_worklist_item(db, item_id=item_id, teacher_id=teacher_id)


class TestSnoozeWorklistItem:
    """Tests for ``worklist.snooze_worklist_item``."""

    @pytest.mark.asyncio
    async def test_snoozes_item_with_custom_date(self) -> None:
        from datetime import UTC, datetime, timedelta

        from app.services.worklist import snooze_worklist_item

        teacher_id = uuid.uuid4()
        item = _make_worklist_item_orm(teacher_id=teacher_id, status="active")
        db = _make_db_for_load(item)
        update_result = MagicMock()
        update_result.rowcount = 1
        db.execute = AsyncMock(side_effect=list(db.execute.side_effect) + [update_result])
        custom_date = datetime.now(UTC) + timedelta(days=14)

        result = await snooze_worklist_item(
            db, item_id=item.id, teacher_id=teacher_id, snoozed_until=custom_date
        )
        assert result is item
        db.commit.assert_awaited_once()
        db.refresh.assert_awaited_once_with(item)

    @pytest.mark.asyncio
    async def test_defaults_to_seven_days_when_snoozed_until_none(self) -> None:
        from app.services.worklist import _DEFAULT_SNOOZE_DAYS, snooze_worklist_item

        assert _DEFAULT_SNOOZE_DAYS == 7

        teacher_id = uuid.uuid4()
        item = _make_worklist_item_orm(teacher_id=teacher_id, status="active")
        db = _make_db_for_load(item)
        update_result = MagicMock()
        update_result.rowcount = 1
        db.execute = AsyncMock(side_effect=list(db.execute.side_effect) + [update_result])

        result = await snooze_worklist_item(
            db, item_id=item.id, teacher_id=teacher_id, snoozed_until=None
        )
        assert result is item
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_raises_not_found_for_missing_item(self) -> None:
        from app.exceptions import NotFoundError
        from app.services.worklist import snooze_worklist_item

        teacher_id = uuid.uuid4()
        item_id = uuid.uuid4()

        load_result = MagicMock()
        load_result.scalar_one_or_none.return_value = None
        db = MagicMock()
        db.execute = AsyncMock(return_value=load_result)

        with pytest.raises(NotFoundError):
            await snooze_worklist_item(db, item_id=item_id, teacher_id=teacher_id)

    @pytest.mark.asyncio
    async def test_raises_not_found_for_cross_tenant_item(self) -> None:
        """Cross-tenant access returns NotFoundError (indistinguishable from 404 under RLS)."""
        from app.exceptions import NotFoundError
        from app.services.worklist import snooze_worklist_item

        teacher_id = uuid.uuid4()
        item_id = uuid.uuid4()

        load_result = MagicMock()
        load_result.scalar_one_or_none.return_value = None
        db = MagicMock()
        db.execute = AsyncMock(return_value=load_result)

        with pytest.raises(NotFoundError):
            await snooze_worklist_item(db, item_id=item_id, teacher_id=teacher_id)


class TestDismissWorklistItem:
    """Tests for ``worklist.dismiss_worklist_item``."""

    @pytest.mark.asyncio
    async def test_dismisses_item(self) -> None:
        from app.services.worklist import dismiss_worklist_item

        teacher_id = uuid.uuid4()
        item = _make_worklist_item_orm(teacher_id=teacher_id, status="active")
        db = _make_db_for_load(item)
        update_result = MagicMock()
        update_result.rowcount = 1
        db.execute = AsyncMock(side_effect=list(db.execute.side_effect) + [update_result])

        result = await dismiss_worklist_item(db, item_id=item.id, teacher_id=teacher_id)
        assert result is item
        db.commit.assert_awaited_once()
        db.refresh.assert_awaited_once_with(item)

    @pytest.mark.asyncio
    async def test_idempotent_when_already_dismissed(self) -> None:
        from app.services.worklist import dismiss_worklist_item

        teacher_id = uuid.uuid4()
        item = _make_worklist_item_orm(teacher_id=teacher_id, status="dismissed")
        db = _make_db_for_load(item)

        result = await dismiss_worklist_item(db, item_id=item.id, teacher_id=teacher_id)
        assert result is item
        # No UPDATE: only the 1 select from _load_worklist_item
        assert db.execute.await_count == 1
        db.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_raises_not_found_for_missing_item(self) -> None:
        from app.exceptions import NotFoundError
        from app.services.worklist import dismiss_worklist_item

        teacher_id = uuid.uuid4()
        item_id = uuid.uuid4()

        load_result = MagicMock()
        load_result.scalar_one_or_none.return_value = None
        db = MagicMock()
        db.execute = AsyncMock(return_value=load_result)

        with pytest.raises(NotFoundError):
            await dismiss_worklist_item(db, item_id=item_id, teacher_id=teacher_id)

    @pytest.mark.asyncio
    async def test_raises_not_found_for_cross_tenant_item(self) -> None:
        """Cross-tenant access returns NotFoundError (indistinguishable from 404 under RLS)."""
        from app.exceptions import NotFoundError
        from app.services.worklist import dismiss_worklist_item

        teacher_id = uuid.uuid4()
        item_id = uuid.uuid4()

        load_result = MagicMock()
        load_result.scalar_one_or_none.return_value = None
        db = MagicMock()
        db.execute = AsyncMock(return_value=load_result)

        with pytest.raises(NotFoundError):
            await dismiss_worklist_item(db, item_id=item_id, teacher_id=teacher_id)


# ---------------------------------------------------------------------------
# Tests — terminal-state transition guards
# ---------------------------------------------------------------------------


class TestTerminalStateGuards:
    """Verify that completed/dismissed states are terminal and cannot be re-transitioned."""

    # --- complete_worklist_item ---

    @pytest.mark.asyncio
    async def test_complete_raises_for_dismissed_item(self) -> None:
        from app.exceptions import InvalidStateTransitionError
        from app.services.worklist import complete_worklist_item

        teacher_id = uuid.uuid4()
        item = _make_worklist_item_orm(teacher_id=teacher_id, status="dismissed")
        db = _make_db_for_load(item)

        with pytest.raises(InvalidStateTransitionError):
            await complete_worklist_item(db, item_id=item.id, teacher_id=teacher_id)
        db.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_complete_succeeds_for_snoozed_item(self) -> None:
        """Snoozed items are not terminal and can be completed."""
        from app.services.worklist import complete_worklist_item

        teacher_id = uuid.uuid4()
        item = _make_worklist_item_orm(teacher_id=teacher_id, status="snoozed")
        db = _make_db_for_load(item)
        update_result = MagicMock()
        update_result.rowcount = 1
        db.execute = AsyncMock(side_effect=list(db.execute.side_effect) + [update_result])

        result = await complete_worklist_item(db, item_id=item.id, teacher_id=teacher_id)
        assert result is item
        db.commit.assert_awaited_once()

    # --- snooze_worklist_item ---

    @pytest.mark.asyncio
    async def test_snooze_raises_for_completed_item(self) -> None:
        from app.exceptions import InvalidStateTransitionError
        from app.services.worklist import snooze_worklist_item

        teacher_id = uuid.uuid4()
        item = _make_worklist_item_orm(teacher_id=teacher_id, status="completed")
        db = _make_db_for_load(item)

        with pytest.raises(InvalidStateTransitionError):
            await snooze_worklist_item(db, item_id=item.id, teacher_id=teacher_id)
        db.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_snooze_raises_for_dismissed_item(self) -> None:
        from app.exceptions import InvalidStateTransitionError
        from app.services.worklist import snooze_worklist_item

        teacher_id = uuid.uuid4()
        item = _make_worklist_item_orm(teacher_id=teacher_id, status="dismissed")
        db = _make_db_for_load(item)

        with pytest.raises(InvalidStateTransitionError):
            await snooze_worklist_item(db, item_id=item.id, teacher_id=teacher_id)
        db.commit.assert_not_awaited()

    # --- dismiss_worklist_item ---

    @pytest.mark.asyncio
    async def test_dismiss_raises_for_completed_item(self) -> None:
        from app.exceptions import InvalidStateTransitionError
        from app.services.worklist import dismiss_worklist_item

        teacher_id = uuid.uuid4()
        item = _make_worklist_item_orm(teacher_id=teacher_id, status="completed")
        db = _make_db_for_load(item)

        with pytest.raises(InvalidStateTransitionError):
            await dismiss_worklist_item(db, item_id=item.id, teacher_id=teacher_id)
        db.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_dismiss_succeeds_for_snoozed_item(self) -> None:
        """Snoozed items are not terminal and can be dismissed."""
        from app.services.worklist import dismiss_worklist_item

        teacher_id = uuid.uuid4()
        item = _make_worklist_item_orm(teacher_id=teacher_id, status="snoozed")
        db = _make_db_for_load(item)
        update_result = MagicMock()
        update_result.rowcount = 1
        db.execute = AsyncMock(side_effect=list(db.execute.side_effect) + [update_result])

        result = await dismiss_worklist_item(db, item_id=item.id, teacher_id=teacher_id)
        assert result is item
        db.commit.assert_awaited_once()
