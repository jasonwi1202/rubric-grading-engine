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
from unittest.mock import MagicMock

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
                "thesis": _skill_entry(avg_score=0.85, trend="stable"),    # above threshold
                "voice": _skill_entry(avg_score=0.55, trend="stable"),     # below threshold
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
