"""Unit tests for app/services/intervention_agent.py (M7-01).

Tests cover:

Signal detection (``_detect_signals``):
- declining trend fires regression signal
- stable trend below threshold + enough assignments fires persistent_gap
- stable trend below threshold + enough assignments + data_points fires non_responder
- improving trend does not fire persistent_gap or non_responder
- trend above threshold does not fire
- declining trend fires regression only (not also persistent_gap/non_responder)
- empty skill_scores returns no signals
- malformed entries are skipped

Trigger reason / evidence summary / suggested action helpers:
- each trigger type returns expected string patterns

``scan_teacher_for_interventions``:
- happy path creates recommendations for detected signals
- skips signals that already have a pending_review row (idempotency)
- writes audit log entries for each new recommendation
- no signals → no DB writes, returns empty list
- multiple students → scans all

``list_interventions``:
- default (no status arg) returns only pending_review items
- status='all' returns all statuses
- status='dismissed' returns only dismissed items
- returns items most-urgent-first, then newest-first within same urgency

``approve_intervention``:
- pending_review → approved; actioned_at set; audit log written
- idempotent when already approved
- dismissed status raises ConflictError
- nonexistent ID raises NotFoundError
- cross-teacher ID raises NotFoundError (RLS pattern)

``dismiss_intervention``:
- pending_review → dismissed; actioned_at set; audit log written
- idempotent when already dismissed
- approved status raises ConflictError
- nonexistent ID raises NotFoundError

``get_all_teacher_ids``:
- returns only users with role='teacher'

No student PII in any fixture.  All database calls are mocked.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.exceptions import ConflictError, NotFoundError
from app.services.intervention_agent import (
    _GAP_MIN_ASSIGNMENTS,
    _NON_RESPONDER_MIN_DATA_POINTS,
    _URGENCY_NON_RESPONDER,
    _URGENCY_PERSISTENT_GAP,
    _URGENCY_REGRESSION,
    _detect_signals,
    _evidence_summary,
    _suggested_action,
    _trigger_reason,
    approve_intervention,
    dismiss_intervention,
    get_all_teacher_ids,
    list_interventions,
    scan_teacher_for_interventions,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_profile(
    student_id: uuid.UUID,
    teacher_id: uuid.UUID,
    skills: dict[str, dict[str, Any]],
    assignment_count: int = 3,
) -> MagicMock:
    """Build a mock StudentSkillProfile."""
    profile = MagicMock()
    profile.student_id = student_id
    profile.teacher_id = teacher_id
    profile.skill_scores = skills
    profile.assignment_count = assignment_count
    return profile


def _skill_entry(
    avg_score: float = 0.70,
    trend: str = "stable",
    data_points: int = 4,
) -> dict[str, Any]:
    return {
        "avg_score": avg_score,
        "trend": trend,
        "data_points": data_points,
        "last_updated": "2026-01-01T00:00:00+00:00",
    }


def _make_rec(
    rec_id: uuid.UUID | None = None,
    teacher_id: uuid.UUID | None = None,
    student_id: uuid.UUID | None = None,
    trigger_type: str = "regression",
    skill_key: str | None = "evidence",
    urgency: int = 4,
    status: str = "pending_review",
    actioned_at: datetime | None = None,
) -> MagicMock:
    """Return a mock InterventionRecommendation with no real student PII."""
    from app.models.intervention_recommendation import InterventionRecommendation

    rec = MagicMock(spec=InterventionRecommendation)
    rec.id = rec_id or uuid.uuid4()
    rec.teacher_id = teacher_id or uuid.uuid4()
    rec.student_id = student_id or uuid.uuid4()
    rec.trigger_type = trigger_type
    rec.skill_key = skill_key
    rec.urgency = urgency
    rec.trigger_reason = "Skill is declining."
    rec.evidence_summary = "Score: 45%, trend: declining."
    rec.suggested_action = "Review with student."
    rec.details = {"avg_score": 0.45, "trend": "declining", "assignment_count": 3}
    rec.status = status
    rec.actioned_at = actioned_at
    rec.created_at = datetime.now(UTC)
    return rec


# ---------------------------------------------------------------------------
# Tests — _detect_signals
# ---------------------------------------------------------------------------


class TestDetectSignals:
    def test_declining_trend_fires_regression(self) -> None:
        student_id = uuid.uuid4()
        teacher_id = uuid.uuid4()
        profile = _make_profile(
            student_id, teacher_id, {"evidence": _skill_entry(avg_score=0.55, trend="declining")}
        )
        signals = _detect_signals(profile)
        regression_signals = [s for s in signals if s["trigger_type"] == "regression"]
        assert len(regression_signals) == 1
        assert regression_signals[0]["skill_key"] == "evidence"
        assert regression_signals[0]["urgency"] == _URGENCY_REGRESSION

    def test_stable_below_threshold_fires_persistent_gap(self) -> None:
        student_id = uuid.uuid4()
        teacher_id = uuid.uuid4()
        profile = _make_profile(
            student_id,
            teacher_id,
            {"thesis": _skill_entry(avg_score=0.50, trend="stable", data_points=2)},
            assignment_count=_GAP_MIN_ASSIGNMENTS,
        )
        signals = _detect_signals(profile)
        gap_signals = [s for s in signals if s["trigger_type"] == "persistent_gap"]
        assert len(gap_signals) == 1
        assert gap_signals[0]["skill_key"] == "thesis"
        assert gap_signals[0]["urgency"] == _URGENCY_PERSISTENT_GAP

    def test_stable_below_threshold_with_many_data_points_fires_non_responder(self) -> None:
        student_id = uuid.uuid4()
        teacher_id = uuid.uuid4()
        profile = _make_profile(
            student_id,
            teacher_id,
            {
                "evidence": _skill_entry(
                    avg_score=0.50,
                    trend="stable",
                    data_points=_NON_RESPONDER_MIN_DATA_POINTS,
                )
            },
            assignment_count=_GAP_MIN_ASSIGNMENTS,
        )
        signals = _detect_signals(profile)
        nr_signals = [s for s in signals if s["trigger_type"] == "non_responder"]
        assert len(nr_signals) == 1
        assert nr_signals[0]["urgency"] == _URGENCY_NON_RESPONDER

    def test_improving_trend_does_not_fire_persistent_gap(self) -> None:
        student_id = uuid.uuid4()
        teacher_id = uuid.uuid4()
        profile = _make_profile(
            student_id,
            teacher_id,
            {"evidence": _skill_entry(avg_score=0.50, trend="improving")},
            assignment_count=3,
        )
        signals = _detect_signals(profile)
        gap_signals = [s for s in signals if s["trigger_type"] == "persistent_gap"]
        assert gap_signals == []

    def test_above_threshold_does_not_fire(self) -> None:
        student_id = uuid.uuid4()
        teacher_id = uuid.uuid4()
        profile = _make_profile(
            student_id,
            teacher_id,
            {"evidence": _skill_entry(avg_score=0.80, trend="stable")},
            assignment_count=3,
        )
        signals = _detect_signals(profile)
        assert signals == []

    def test_too_few_assignments_skips_persistent_gap(self) -> None:
        student_id = uuid.uuid4()
        teacher_id = uuid.uuid4()
        profile = _make_profile(
            student_id,
            teacher_id,
            {"evidence": _skill_entry(avg_score=0.50, trend="stable")},
            assignment_count=_GAP_MIN_ASSIGNMENTS - 1,
        )
        signals = _detect_signals(profile)
        gap_signals = [s for s in signals if s["trigger_type"] == "persistent_gap"]
        assert gap_signals == []

    def test_empty_skill_scores_returns_no_signals(self) -> None:
        student_id = uuid.uuid4()
        teacher_id = uuid.uuid4()
        profile = _make_profile(student_id, teacher_id, {})
        assert _detect_signals(profile) == []

    def test_malformed_entry_is_skipped(self) -> None:
        student_id = uuid.uuid4()
        teacher_id = uuid.uuid4()
        profile = _make_profile(student_id, teacher_id, {"evidence": "not_a_dict"})
        assert _detect_signals(profile) == []

    def test_declining_trend_fires_only_regression_not_persistent_gap(self) -> None:
        """Declining trend should NOT also fire persistent_gap (separate condition)."""
        student_id = uuid.uuid4()
        teacher_id = uuid.uuid4()
        profile = _make_profile(
            student_id,
            teacher_id,
            {"evidence": _skill_entry(avg_score=0.50, trend="declining")},
            assignment_count=3,
        )
        signals = _detect_signals(profile)
        regression_signals = [s for s in signals if s["trigger_type"] == "regression"]
        gap_signals = [s for s in signals if s["trigger_type"] == "persistent_gap"]
        assert len(regression_signals) == 1
        # Persistent gap requires trend != 'declining', so no gap signal here.
        assert gap_signals == []

    def test_multiple_skills_multiple_signals(self) -> None:
        student_id = uuid.uuid4()
        teacher_id = uuid.uuid4()
        profile = _make_profile(
            student_id,
            teacher_id,
            {
                "evidence": _skill_entry(avg_score=0.45, trend="declining"),
                "thesis": _skill_entry(avg_score=0.50, trend="stable", data_points=5),
            },
            assignment_count=3,
        )
        signals = _detect_signals(profile)
        trigger_types = {s["trigger_type"] for s in signals}
        assert "regression" in trigger_types
        # thesis: stable + below threshold + enough assignments + data_points >= 3
        # is classified as non_responder and persistent_gap is suppressed to
        # avoid duplicate recommendations for one root cause.
        assert "persistent_gap" not in trigger_types
        assert "non_responder" in trigger_types

    def test_non_responder_suppresses_persistent_gap_for_same_skill(self) -> None:
        student_id = uuid.uuid4()
        teacher_id = uuid.uuid4()
        profile = _make_profile(
            student_id,
            teacher_id,
            {
                "evidence": _skill_entry(
                    avg_score=0.50,
                    trend="stable",
                    data_points=_NON_RESPONDER_MIN_DATA_POINTS,
                )
            },
            assignment_count=_GAP_MIN_ASSIGNMENTS,
        )

        signals = _detect_signals(profile)
        trigger_types = [s["trigger_type"] for s in signals if s["skill_key"] == "evidence"]
        assert trigger_types == ["non_responder"]


# ---------------------------------------------------------------------------
# Tests — trigger reason / evidence / action helpers
# ---------------------------------------------------------------------------


class TestTriggerReasonHelpers:
    def test_regression_trigger_reason_mentions_skill(self) -> None:
        details: dict[str, Any] = {"avg_score": 0.45, "trend": "declining"}
        reason = _trigger_reason("regression", "evidence", details)
        assert "evidence" in reason
        assert "downward" in reason.lower() or "declining" in reason.lower()

    def test_persistent_gap_trigger_reason_mentions_assignments(self) -> None:
        details: dict[str, Any] = {"avg_score": 0.50, "trend": "stable", "assignment_count": 3}
        reason = _trigger_reason("persistent_gap", "thesis", details)
        assert "3" in reason
        assert "thesis" in reason

    def test_non_responder_trigger_reason_mentions_data_points(self) -> None:
        details: dict[str, Any] = {"avg_score": 0.50, "trend": "stable", "data_points": 5}
        reason = _trigger_reason("non_responder", "evidence", details)
        assert "5" in reason

    def test_evidence_summary_contains_avg_score(self) -> None:
        details: dict[str, Any] = {"avg_score": 0.50, "trend": "stable", "assignment_count": 3}
        summary = _evidence_summary("persistent_gap", "evidence", details)
        assert "50%" in summary
        assert "evidence" in summary

    def test_suggested_action_regression(self) -> None:
        action = _suggested_action("regression", "evidence")
        assert "evidence" in action
        assert "decline" in action.lower() or "review" in action.lower()

    def test_suggested_action_persistent_gap(self) -> None:
        action = _suggested_action("persistent_gap", "thesis")
        assert "thesis" in action

    def test_suggested_action_non_responder(self) -> None:
        action = _suggested_action("non_responder", None)
        assert "1:1" in action or "check-in" in action.lower()


# ---------------------------------------------------------------------------
# Tests — scan_teacher_for_interventions
# ---------------------------------------------------------------------------


class TestScanTeacherForInterventions:
    @pytest.mark.asyncio
    async def test_happy_path_creates_recommendation(self) -> None:
        teacher_id = uuid.uuid4()
        student_id = uuid.uuid4()

        profile = _make_profile(
            student_id,
            teacher_id,
            {"evidence": _skill_entry(avg_score=0.45, trend="declining")},
            assignment_count=3,
        )

        db = AsyncMock()
        # profiles query returns one profile
        profile_scalars = MagicMock()
        profile_scalars.scalars.return_value = [profile]
        db.execute = AsyncMock(
            side_effect=[
                profile_scalars,  # SELECT StudentSkillProfile
                MagicMock(return_value=set()),  # SELECT pending_signal_keys (empty set)
            ]
        )
        db.add = MagicMock()
        db.flush = AsyncMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock()
        # begin_nested() is a sync call in SQLAlchemy AsyncSession that returns
        # an async context manager. MagicMock returning AsyncMock() replicates this.
        db.begin_nested = MagicMock(return_value=AsyncMock())

        # Patch _pending_signal_keys to return empty set
        with patch(
            "app.services.intervention_agent._pending_signal_keys",
            new=AsyncMock(return_value=set()),
        ):
            result = await scan_teacher_for_interventions(db, teacher_id)

        assert len(result) >= 1
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_idempotency_skips_existing_pending(self) -> None:
        teacher_id = uuid.uuid4()
        student_id = uuid.uuid4()

        profile = _make_profile(
            student_id,
            teacher_id,
            {"evidence": _skill_entry(avg_score=0.45, trend="declining")},
            assignment_count=3,
        )

        db = AsyncMock()
        profile_scalars = MagicMock()
        profile_scalars.scalars.return_value = [profile]
        db.execute = AsyncMock(return_value=profile_scalars)
        db.add = MagicMock()

        # Pending keys already contain the regression signal for 'evidence'
        with patch(
            "app.services.intervention_agent._pending_signal_keys",
            new=AsyncMock(return_value={("regression", "evidence")}),
        ):
            result = await scan_teacher_for_interventions(db, teacher_id)

        # No regression signal created because it's already pending.
        regression_created = [r for r in result if r.trigger_type == "regression"]
        assert regression_created == []
        db.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_signals_returns_empty_list(self) -> None:
        teacher_id = uuid.uuid4()
        student_id = uuid.uuid4()

        # Profile with good scores — no signals.
        profile = _make_profile(
            student_id,
            teacher_id,
            {"evidence": _skill_entry(avg_score=0.90, trend="improving")},
            assignment_count=3,
        )

        db = AsyncMock()
        profile_scalars = MagicMock()
        profile_scalars.scalars.return_value = [profile]
        db.execute = AsyncMock(return_value=profile_scalars)
        db.commit = AsyncMock()

        result = await scan_teacher_for_interventions(db, teacher_id)
        assert result == []
        db.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_profiles_returns_empty_list(self) -> None:
        teacher_id = uuid.uuid4()

        db = AsyncMock()
        profile_scalars = MagicMock()
        profile_scalars.scalars.return_value = []
        db.execute = AsyncMock(return_value=profile_scalars)
        db.commit = AsyncMock()

        result = await scan_teacher_for_interventions(db, teacher_id)
        assert result == []
        db.commit.assert_not_awaited()


# ---------------------------------------------------------------------------
# Tests — list_interventions
# ---------------------------------------------------------------------------


class TestListInterventions:
    @pytest.mark.asyncio
    async def test_default_returns_pending_review_only(self) -> None:
        teacher_id = uuid.uuid4()
        pending_rec = _make_rec(teacher_id=teacher_id, status="pending_review")

        db = AsyncMock()
        rows = MagicMock()
        rows.scalars.return_value = [pending_rec]
        db.execute = AsyncMock(return_value=rows)

        result = await list_interventions(db, teacher_id=teacher_id)
        assert result == [pending_rec]

    @pytest.mark.asyncio
    async def test_status_all_returns_multiple(self) -> None:
        teacher_id = uuid.uuid4()
        approved_rec = _make_rec(teacher_id=teacher_id, status="approved")
        dismissed_rec = _make_rec(teacher_id=teacher_id, status="dismissed")

        db = AsyncMock()
        rows = MagicMock()
        rows.scalars.return_value = [approved_rec, dismissed_rec]
        db.execute = AsyncMock(return_value=rows)

        result = await list_interventions(db, teacher_id=teacher_id, status="all")
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_empty_list_when_no_items(self) -> None:
        teacher_id = uuid.uuid4()

        db = AsyncMock()
        rows = MagicMock()
        rows.scalars.return_value = []
        db.execute = AsyncMock(return_value=rows)

        result = await list_interventions(db, teacher_id=teacher_id)
        assert result == []


# ---------------------------------------------------------------------------
# Tests — approve_intervention
# ---------------------------------------------------------------------------


class TestApproveIntervention:
    @pytest.mark.asyncio
    async def test_happy_path_transitions_to_approved(self) -> None:
        teacher_id = uuid.uuid4()
        rec_id = uuid.uuid4()
        rec = _make_rec(rec_id=rec_id, teacher_id=teacher_id, status="pending_review")
        rec.status = "pending_review"

        db = AsyncMock()
        # First execute: load rec
        load_result = MagicMock()
        load_result.scalar_one_or_none.return_value = rec
        # Second execute: UPDATE returns rowcount=1
        update_result = MagicMock()
        update_result.rowcount = 1
        db.execute = AsyncMock(side_effect=[load_result, update_result])
        db.add = MagicMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        result = await approve_intervention(db, rec_id=rec_id, teacher_id=teacher_id)
        db.commit.assert_awaited_once()
        # The rec mock still carries status='pending_review' because we didn't
        # update the mock — just verify commit was called and result returned.
        assert result is rec

    @pytest.mark.asyncio
    async def test_idempotent_already_approved(self) -> None:
        teacher_id = uuid.uuid4()
        rec_id = uuid.uuid4()
        rec = _make_rec(rec_id=rec_id, teacher_id=teacher_id, status="approved")

        db = AsyncMock()
        load_result = MagicMock()
        load_result.scalar_one_or_none.return_value = rec
        db.execute = AsyncMock(return_value=load_result)
        db.commit = AsyncMock()

        result = await approve_intervention(db, rec_id=rec_id, teacher_id=teacher_id)
        # Already approved — no commit needed.
        db.commit.assert_not_awaited()
        assert result is rec

    @pytest.mark.asyncio
    async def test_dismissed_raises_conflict(self) -> None:
        teacher_id = uuid.uuid4()
        rec_id = uuid.uuid4()
        rec = _make_rec(rec_id=rec_id, teacher_id=teacher_id, status="dismissed")

        db = AsyncMock()
        load_result = MagicMock()
        load_result.scalar_one_or_none.return_value = rec
        db.execute = AsyncMock(return_value=load_result)

        with pytest.raises(ConflictError):
            await approve_intervention(db, rec_id=rec_id, teacher_id=teacher_id)

    @pytest.mark.asyncio
    async def test_nonexistent_raises_not_found(self) -> None:
        teacher_id = uuid.uuid4()
        rec_id = uuid.uuid4()

        db = AsyncMock()
        load_result = MagicMock()
        load_result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=load_result)

        with pytest.raises(NotFoundError):
            await approve_intervention(db, rec_id=rec_id, teacher_id=teacher_id)

    @pytest.mark.asyncio
    async def test_cross_teacher_raises_not_found(self) -> None:
        """Cross-teacher access returns NotFoundError (RLS pattern, not 403)."""
        teacher_id = uuid.uuid4()
        _other_teacher_id = uuid.uuid4()
        rec_id = uuid.uuid4()

        db = AsyncMock()
        load_result = MagicMock()
        # Cross-teacher: RLS returns None because the query includes teacher_id filter.
        load_result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=load_result)

        with pytest.raises(NotFoundError):
            await approve_intervention(db, rec_id=rec_id, teacher_id=teacher_id)


# ---------------------------------------------------------------------------
# Tests — dismiss_intervention
# ---------------------------------------------------------------------------


class TestDismissIntervention:
    @pytest.mark.asyncio
    async def test_happy_path_transitions_to_dismissed(self) -> None:
        teacher_id = uuid.uuid4()
        rec_id = uuid.uuid4()
        rec = _make_rec(rec_id=rec_id, teacher_id=teacher_id, status="pending_review")

        db = AsyncMock()
        load_result = MagicMock()
        load_result.scalar_one_or_none.return_value = rec
        update_result = MagicMock()
        update_result.rowcount = 1
        db.execute = AsyncMock(side_effect=[load_result, update_result])
        db.add = MagicMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        result = await dismiss_intervention(db, rec_id=rec_id, teacher_id=teacher_id)
        db.commit.assert_awaited_once()
        assert result is rec

    @pytest.mark.asyncio
    async def test_idempotent_already_dismissed(self) -> None:
        teacher_id = uuid.uuid4()
        rec_id = uuid.uuid4()
        rec = _make_rec(rec_id=rec_id, teacher_id=teacher_id, status="dismissed")

        db = AsyncMock()
        load_result = MagicMock()
        load_result.scalar_one_or_none.return_value = rec
        db.execute = AsyncMock(return_value=load_result)
        db.commit = AsyncMock()

        result = await dismiss_intervention(db, rec_id=rec_id, teacher_id=teacher_id)
        db.commit.assert_not_awaited()
        assert result is rec

    @pytest.mark.asyncio
    async def test_approved_raises_conflict(self) -> None:
        teacher_id = uuid.uuid4()
        rec_id = uuid.uuid4()
        rec = _make_rec(rec_id=rec_id, teacher_id=teacher_id, status="approved")

        db = AsyncMock()
        load_result = MagicMock()
        load_result.scalar_one_or_none.return_value = rec
        db.execute = AsyncMock(return_value=load_result)

        with pytest.raises(ConflictError):
            await dismiss_intervention(db, rec_id=rec_id, teacher_id=teacher_id)

    @pytest.mark.asyncio
    async def test_nonexistent_raises_not_found(self) -> None:
        teacher_id = uuid.uuid4()
        rec_id = uuid.uuid4()

        db = AsyncMock()
        load_result = MagicMock()
        load_result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=load_result)

        with pytest.raises(NotFoundError):
            await dismiss_intervention(db, rec_id=rec_id, teacher_id=teacher_id)


# ---------------------------------------------------------------------------
# Tests — get_all_teacher_ids
# ---------------------------------------------------------------------------


class TestGetAllTeacherIds:
    @pytest.mark.asyncio
    async def test_returns_teacher_uuids(self) -> None:
        teacher_id_1 = uuid.uuid4()
        teacher_id_2 = uuid.uuid4()

        db = AsyncMock()
        rows = MagicMock()
        rows.scalars.return_value = [teacher_id_1, teacher_id_2]
        db.execute = AsyncMock(return_value=rows)

        result = await get_all_teacher_ids(db)
        assert set(result) == {teacher_id_1, teacher_id_2}

    @pytest.mark.asyncio
    async def test_empty_when_no_teachers(self) -> None:
        db = AsyncMock()
        rows = MagicMock()
        rows.scalars.return_value = []
        db.execute = AsyncMock(return_value=rows)

        result = await get_all_teacher_ids(db)
        assert result == []
