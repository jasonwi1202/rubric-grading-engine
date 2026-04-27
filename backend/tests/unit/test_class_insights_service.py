"""Unit tests for the class insights and assignment analytics service.

Tests verify:
- Correct aggregation of skill averages, score distributions, and common issues.
- Per-criterion analytics computation for assignment analytics.
- Tenant isolation: cross-teacher access raises ForbiddenError.
- Edge cases: no locked grades, missing criteria in snapshot.

All DB calls are mocked with AsyncMock.  No real database is required.
No student PII appears in any fixture or assertion.
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.exceptions import ForbiddenError, NotFoundError

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _make_db() -> AsyncMock:
    """Create a minimal async DB mock."""
    db = AsyncMock()
    return db


def _make_row(**kwargs: Any) -> MagicMock:
    row = MagicMock()
    for k, v in kwargs.items():
        setattr(row, k, v)
    return row


def _make_class_row(class_id: uuid.UUID, teacher_id: uuid.UUID) -> MagicMock:
    return _make_row(id=class_id, teacher_id=teacher_id)


def _snapshot_with_criteria(criteria: list[dict[str, Any]]) -> dict[str, Any]:
    return {"criteria": criteria}


def _make_criterion(
    crit_id: str,
    name: str,
    min_score: int = 0,
    max_score: int = 4,
    display_order: int = 0,
) -> dict[str, Any]:
    return {
        "id": crit_id,
        "name": name,
        "min_score": min_score,
        "max_score": max_score,
        "display_order": display_order,
    }


# ---------------------------------------------------------------------------
# _normalise_score (internal helper — tested via service internals)
# ---------------------------------------------------------------------------


class TestNormaliseScore:
    def test_midpoint(self) -> None:
        from app.services.class_insights import _normalise_score

        assert _normalise_score(2, 0, 4) == pytest.approx(0.5)

    def test_max_score(self) -> None:
        from app.services.class_insights import _normalise_score

        assert _normalise_score(4, 0, 4) == pytest.approx(1.0)

    def test_min_score(self) -> None:
        from app.services.class_insights import _normalise_score

        assert _normalise_score(0, 0, 4) == pytest.approx(0.0)

    def test_clamps_below_zero(self) -> None:
        from app.services.class_insights import _normalise_score

        assert _normalise_score(-1, 0, 4) == pytest.approx(0.0)

    def test_clamps_above_one(self) -> None:
        from app.services.class_insights import _normalise_score

        assert _normalise_score(5, 0, 4) == pytest.approx(1.0)

    def test_degenerate_range_returns_one(self) -> None:
        from app.services.class_insights import _normalise_score

        assert _normalise_score(3, 3, 3) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# _bucket_index (internal helper)
# ---------------------------------------------------------------------------


class TestBucketIndex:
    def test_zero_maps_to_first_bucket(self) -> None:
        from app.services.class_insights import _bucket_index

        assert _bucket_index(0.0) == 0

    def test_one_maps_to_last_bucket(self) -> None:
        from app.services.class_insights import _bucket_index

        assert _bucket_index(1.0) == 4

    def test_boundary_values(self) -> None:
        from app.services.class_insights import _bucket_index

        assert _bucket_index(0.19) == 0
        assert _bucket_index(0.20) == 1
        assert _bucket_index(0.39) == 1
        assert _bucket_index(0.40) == 2
        assert _bucket_index(0.59) == 2
        assert _bucket_index(0.60) == 3
        assert _bucket_index(0.79) == 3
        assert _bucket_index(0.80) == 4


# ---------------------------------------------------------------------------
# _build_distribution
# ---------------------------------------------------------------------------


class TestBuildDistribution:
    def test_five_buckets_always_returned(self) -> None:
        from app.services.class_insights import _build_distribution

        dist = _build_distribution([0.1, 0.3, 0.5, 0.7, 0.9])
        assert len(dist) == 5

    def test_correct_bucket_counts(self) -> None:
        from app.services.class_insights import _build_distribution

        dist = _build_distribution([0.1, 0.1, 0.5])
        counts = {b.label: b.count for b in dist}
        assert counts["0-20%"] == 2
        assert counts["40-60%"] == 1
        assert counts["20-40%"] == 0

    def test_empty_list_returns_all_zeros(self) -> None:
        from app.services.class_insights import _build_distribution

        dist = _build_distribution([])
        assert all(b.count == 0 for b in dist)


# ---------------------------------------------------------------------------
# _assert_class_owned_by
# ---------------------------------------------------------------------------


class TestAssertClassOwnedBy:
    @pytest.mark.asyncio
    async def test_raises_not_found_when_class_missing(self) -> None:
        from app.services.class_insights import _assert_class_owned_by

        db = AsyncMock()
        result = MagicMock()
        result.one_or_none.return_value = None
        db.execute = AsyncMock(return_value=result)

        with pytest.raises(NotFoundError):
            await _assert_class_owned_by(db, uuid.uuid4(), uuid.uuid4())

    @pytest.mark.asyncio
    async def test_raises_forbidden_for_wrong_teacher(self) -> None:
        from app.services.class_insights import _assert_class_owned_by

        teacher_a = uuid.uuid4()
        teacher_b = uuid.uuid4()
        class_id = uuid.uuid4()

        db = AsyncMock()
        row = _make_class_row(class_id, teacher_a)
        result = MagicMock()
        result.one_or_none.return_value = row
        db.execute = AsyncMock(return_value=result)

        with pytest.raises(ForbiddenError):
            await _assert_class_owned_by(db, class_id, teacher_b)

    @pytest.mark.asyncio
    async def test_passes_for_correct_teacher(self) -> None:
        from app.services.class_insights import _assert_class_owned_by

        teacher_id = uuid.uuid4()
        class_id = uuid.uuid4()

        db = AsyncMock()
        row = _make_class_row(class_id, teacher_id)
        result = MagicMock()
        result.one_or_none.return_value = row
        db.execute = AsyncMock(return_value=result)

        # Should not raise.
        await _assert_class_owned_by(db, class_id, teacher_id)


# ---------------------------------------------------------------------------
# _assert_assignment_owned_by
# ---------------------------------------------------------------------------


class TestAssertAssignmentOwnedBy:
    @pytest.mark.asyncio
    async def test_raises_not_found_when_assignment_missing(self) -> None:
        from app.services.class_insights import _assert_assignment_owned_by

        db = AsyncMock()
        result = MagicMock()
        result.one_or_none.return_value = None
        db.execute = AsyncMock(return_value=result)

        with pytest.raises(NotFoundError):
            await _assert_assignment_owned_by(db, uuid.uuid4(), uuid.uuid4())

    @pytest.mark.asyncio
    async def test_raises_forbidden_for_wrong_teacher(self) -> None:
        from app.services.class_insights import _assert_assignment_owned_by

        teacher_a = uuid.uuid4()
        teacher_b = uuid.uuid4()
        assignment_id = uuid.uuid4()
        class_id = uuid.uuid4()

        db = AsyncMock()
        row = _make_row(id=assignment_id, class_id=class_id, teacher_id=teacher_a)
        result = MagicMock()
        result.one_or_none.return_value = row
        db.execute = AsyncMock(return_value=result)

        with pytest.raises(ForbiddenError):
            await _assert_assignment_owned_by(db, assignment_id, teacher_b)


# ---------------------------------------------------------------------------
# get_class_insights
# ---------------------------------------------------------------------------


class TestGetClassInsights:
    @pytest.mark.asyncio
    async def test_returns_empty_insights_when_no_locked_grades(self) -> None:
        """A class with assignments but no locked grades returns zero aggregates."""
        from app.services.class_insights import get_class_insights

        teacher_id = uuid.uuid4()
        class_id = uuid.uuid4()

        db = AsyncMock()

        # 1. Class ownership check
        class_result = MagicMock()
        class_result.one_or_none.return_value = _make_class_row(class_id, teacher_id)

        # 2. Assignment count
        asgn_count_result = MagicMock()
        asgn_count_result.scalar_one.return_value = 2

        # 3. Student count
        student_count_result = MagicMock()
        student_count_result.scalar_one.return_value = 20

        # 4. Locked criterion scores — empty
        scores_result = MagicMock()
        scores_result.all.return_value = []

        db.execute = AsyncMock(
            side_effect=[class_result, asgn_count_result, student_count_result, scores_result]
        )

        insights = await get_class_insights(db, teacher_id, class_id)

        assert insights.class_id == class_id
        assert insights.assignment_count == 2
        assert insights.student_count == 20
        assert insights.graded_essay_count == 0
        assert insights.skill_averages == {}
        assert insights.score_distributions == {}
        assert insights.common_issues == []

    @pytest.mark.asyncio
    async def test_computes_skill_averages_correctly(self) -> None:
        """Skill averages are the mean of normalised criterion scores."""
        from app.services.class_insights import get_class_insights

        teacher_id = uuid.uuid4()
        class_id = uuid.uuid4()
        student_id = uuid.uuid4()
        grade_id = uuid.uuid4()
        crit_id = uuid.uuid4()

        snapshot = _snapshot_with_criteria([
            _make_criterion(str(crit_id), "Thesis Statement", min_score=0, max_score=4),
        ])

        # Two criterion score rows with final_score 2 and 4 → normalised 0.5 and 1.0
        row1 = _make_row(
            student_id=student_id,
            grade_id=grade_id,
            rubric_criterion_id=crit_id,
            final_score=2,
            rubric_snapshot=snapshot,
        )
        row2 = _make_row(
            student_id=student_id,
            grade_id=uuid.uuid4(),
            rubric_criterion_id=crit_id,
            final_score=4,
            rubric_snapshot=snapshot,
        )

        db = AsyncMock()
        class_result = MagicMock()
        class_result.one_or_none.return_value = _make_class_row(class_id, teacher_id)
        asgn_count_result = MagicMock()
        asgn_count_result.scalar_one.return_value = 1
        student_count_result = MagicMock()
        student_count_result.scalar_one.return_value = 1
        scores_result = MagicMock()
        scores_result.all.return_value = [row1, row2]

        db.execute = AsyncMock(
            side_effect=[class_result, asgn_count_result, student_count_result, scores_result]
        )

        insights = await get_class_insights(db, teacher_id, class_id)

        assert "thesis" in insights.skill_averages
        thesis = insights.skill_averages["thesis"]
        # avg of 0.5 and 1.0 = 0.75
        assert thesis.avg_score == pytest.approx(0.75, abs=1e-4)
        assert thesis.data_points == 2

    @pytest.mark.asyncio
    async def test_common_issues_includes_low_scoring_skills(self) -> None:
        """Skills with avg < 0.60 appear in common_issues."""
        from app.services.class_insights import get_class_insights

        teacher_id = uuid.uuid4()
        class_id = uuid.uuid4()
        student_id = uuid.uuid4()
        grade_id = uuid.uuid4()
        crit_id = uuid.uuid4()

        # final_score=1 on a 0-4 scale → normalised 0.25 (below 0.60 threshold)
        snapshot = _snapshot_with_criteria([
            _make_criterion(str(crit_id), "Evidence Use", min_score=0, max_score=4),
        ])
        row = _make_row(
            student_id=student_id,
            grade_id=grade_id,
            rubric_criterion_id=crit_id,
            final_score=1,
            rubric_snapshot=snapshot,
        )

        db = AsyncMock()
        class_result = MagicMock()
        class_result.one_or_none.return_value = _make_class_row(class_id, teacher_id)
        asgn_count_result = MagicMock()
        asgn_count_result.scalar_one.return_value = 1
        student_count_result = MagicMock()
        student_count_result.scalar_one.return_value = 1
        scores_result = MagicMock()
        scores_result.all.return_value = [row]

        db.execute = AsyncMock(
            side_effect=[class_result, asgn_count_result, student_count_result, scores_result]
        )

        insights = await get_class_insights(db, teacher_id, class_id)

        assert len(insights.common_issues) == 1
        issue = insights.common_issues[0]
        assert issue.skill_dimension == "evidence"
        assert issue.avg_score == pytest.approx(0.25, abs=1e-4)
        assert issue.affected_student_count == 1

    @pytest.mark.asyncio
    async def test_common_issues_excludes_high_scoring_skills(self) -> None:
        """Skills with avg ≥ 0.60 do not appear in common_issues."""
        from app.services.class_insights import get_class_insights

        teacher_id = uuid.uuid4()
        class_id = uuid.uuid4()
        student_id = uuid.uuid4()
        grade_id = uuid.uuid4()
        crit_id = uuid.uuid4()

        # final_score=4 on a 0-4 scale → normalised 1.0 (above threshold)
        snapshot = _snapshot_with_criteria([
            _make_criterion(str(crit_id), "Thesis Statement", min_score=0, max_score=4),
        ])
        row = _make_row(
            student_id=student_id,
            grade_id=grade_id,
            rubric_criterion_id=crit_id,
            final_score=4,
            rubric_snapshot=snapshot,
        )

        db = AsyncMock()
        class_result = MagicMock()
        class_result.one_or_none.return_value = _make_class_row(class_id, teacher_id)
        asgn_count_result = MagicMock()
        asgn_count_result.scalar_one.return_value = 1
        student_count_result = MagicMock()
        student_count_result.scalar_one.return_value = 1
        scores_result = MagicMock()
        scores_result.all.return_value = [row]

        db.execute = AsyncMock(
            side_effect=[class_result, asgn_count_result, student_count_result, scores_result]
        )

        insights = await get_class_insights(db, teacher_id, class_id)

        assert insights.common_issues == []

    @pytest.mark.asyncio
    async def test_raises_not_found_for_missing_class(self) -> None:
        from app.services.class_insights import get_class_insights

        db = AsyncMock()
        result = MagicMock()
        result.one_or_none.return_value = None
        db.execute = AsyncMock(return_value=result)

        with pytest.raises(NotFoundError):
            await get_class_insights(db, uuid.uuid4(), uuid.uuid4())

    @pytest.mark.asyncio
    async def test_raises_forbidden_for_wrong_teacher(self) -> None:
        from app.services.class_insights import get_class_insights

        teacher_a = uuid.uuid4()
        teacher_b = uuid.uuid4()
        class_id = uuid.uuid4()

        db = AsyncMock()
        result = MagicMock()
        result.one_or_none.return_value = _make_class_row(class_id, teacher_a)
        db.execute = AsyncMock(return_value=result)

        with pytest.raises(ForbiddenError):
            await get_class_insights(db, teacher_b, class_id)

    @pytest.mark.asyncio
    async def test_skips_criteria_missing_from_snapshot(self) -> None:
        """Criterion scores whose ID is absent from the snapshot are skipped silently."""
        from app.services.class_insights import get_class_insights

        teacher_id = uuid.uuid4()
        class_id = uuid.uuid4()
        student_id = uuid.uuid4()
        grade_id = uuid.uuid4()
        unknown_crit_id = uuid.uuid4()

        # Snapshot contains no criteria (empty list)
        snapshot = _snapshot_with_criteria([])
        row = _make_row(
            student_id=student_id,
            grade_id=grade_id,
            rubric_criterion_id=unknown_crit_id,
            final_score=3,
            rubric_snapshot=snapshot,
        )

        db = AsyncMock()
        class_result = MagicMock()
        class_result.one_or_none.return_value = _make_class_row(class_id, teacher_id)
        asgn_count_result = MagicMock()
        asgn_count_result.scalar_one.return_value = 1
        student_count_result = MagicMock()
        student_count_result.scalar_one.return_value = 1
        scores_result = MagicMock()
        scores_result.all.return_value = [row]

        db.execute = AsyncMock(
            side_effect=[class_result, asgn_count_result, student_count_result, scores_result]
        )

        insights = await get_class_insights(db, teacher_id, class_id)

        # Unknown criterion is skipped — no skill averages produced.
        assert insights.skill_averages == {}


# ---------------------------------------------------------------------------
# get_assignment_analytics
# ---------------------------------------------------------------------------


class TestGetAssignmentAnalytics:
    def _make_assignment_orm(
        self,
        assignment_id: uuid.UUID,
        class_id: uuid.UUID,
        snapshot: dict[str, Any],
    ) -> MagicMock:
        obj = MagicMock()
        obj.id = assignment_id
        obj.class_id = class_id
        obj.rubric_snapshot = snapshot
        return obj

    @pytest.mark.asyncio
    async def test_returns_analytics_with_locked_grades(self) -> None:
        from app.services.class_insights import get_assignment_analytics

        teacher_id = uuid.uuid4()
        assignment_id = uuid.uuid4()
        class_id = uuid.uuid4()
        crit_id = uuid.uuid4()

        snapshot = _snapshot_with_criteria([
            _make_criterion(str(crit_id), "Thesis Statement", min_score=0, max_score=4),
        ])

        db = AsyncMock()

        # 1. Ownership check
        ownership_row = _make_row(id=assignment_id, class_id=class_id, teacher_id=teacher_id)
        ownership_result = MagicMock()
        ownership_result.one_or_none.return_value = ownership_row

        # 2. Full assignment fetch
        assignment_obj = self._make_assignment_orm(assignment_id, class_id, snapshot)
        assignment_result = MagicMock()
        assignment_result.scalar_one.return_value = assignment_obj

        # 3. Total essay count
        total_count_result = MagicMock()
        total_count_result.scalar_one.return_value = 10

        # 4. Locked essay count
        locked_count_result = MagicMock()
        locked_count_result.scalar_one.return_value = 8

        # 5. Criterion scores — two rows with scores 2 and 4
        score_row1 = _make_row(rubric_criterion_id=crit_id, final_score=2)
        score_row2 = _make_row(rubric_criterion_id=crit_id, final_score=4)
        scores_result = MagicMock()
        scores_result.all.return_value = [score_row1, score_row2]

        db.execute = AsyncMock(
            side_effect=[
                ownership_result,
                assignment_result,
                total_count_result,
                locked_count_result,
                scores_result,
            ]
        )

        analytics = await get_assignment_analytics(db, teacher_id, assignment_id)

        assert analytics.assignment_id == assignment_id
        assert analytics.class_id == class_id
        assert analytics.total_essay_count == 10
        assert analytics.locked_essay_count == 8
        assert len(analytics.criterion_analytics) == 1
        crit_analytics = analytics.criterion_analytics[0]
        assert crit_analytics.criterion_name == "Thesis Statement"
        assert crit_analytics.skill_dimension == "thesis"
        # avg of (2 and 4) on 0-4 scale → raw avg = 3.0, normalised = 0.75
        assert crit_analytics.avg_score == pytest.approx(3.0, abs=1e-4)
        assert crit_analytics.avg_normalized_score == pytest.approx(0.75, abs=1e-4)
        assert analytics.overall_avg_normalized_score == pytest.approx(0.75, abs=1e-4)

    @pytest.mark.asyncio
    async def test_overall_avg_is_none_when_no_locked_grades(self) -> None:
        from app.services.class_insights import get_assignment_analytics

        teacher_id = uuid.uuid4()
        assignment_id = uuid.uuid4()
        class_id = uuid.uuid4()
        crit_id = uuid.uuid4()

        snapshot = _snapshot_with_criteria([
            _make_criterion(str(crit_id), "Thesis Statement", min_score=0, max_score=4),
        ])

        db = AsyncMock()
        ownership_row = _make_row(id=assignment_id, class_id=class_id, teacher_id=teacher_id)
        ownership_result = MagicMock()
        ownership_result.one_or_none.return_value = ownership_row
        assignment_obj = self._make_assignment_orm(assignment_id, class_id, snapshot)
        assignment_result = MagicMock()
        assignment_result.scalar_one.return_value = assignment_obj
        total_count_result = MagicMock()
        total_count_result.scalar_one.return_value = 5
        locked_count_result = MagicMock()
        locked_count_result.scalar_one.return_value = 0
        scores_result = MagicMock()
        scores_result.all.return_value = []

        db.execute = AsyncMock(
            side_effect=[
                ownership_result,
                assignment_result,
                total_count_result,
                locked_count_result,
                scores_result,
            ]
        )

        analytics = await get_assignment_analytics(db, teacher_id, assignment_id)

        assert analytics.overall_avg_normalized_score is None
        assert analytics.locked_essay_count == 0

    @pytest.mark.asyncio
    async def test_raises_not_found_for_missing_assignment(self) -> None:
        from app.services.class_insights import get_assignment_analytics

        db = AsyncMock()
        result = MagicMock()
        result.one_or_none.return_value = None
        db.execute = AsyncMock(return_value=result)

        with pytest.raises(NotFoundError):
            await get_assignment_analytics(db, uuid.uuid4(), uuid.uuid4())

    @pytest.mark.asyncio
    async def test_raises_forbidden_for_wrong_teacher(self) -> None:
        from app.services.class_insights import get_assignment_analytics

        teacher_a = uuid.uuid4()
        teacher_b = uuid.uuid4()
        assignment_id = uuid.uuid4()
        class_id = uuid.uuid4()

        db = AsyncMock()
        row = _make_row(id=assignment_id, class_id=class_id, teacher_id=teacher_a)
        result = MagicMock()
        result.one_or_none.return_value = row
        db.execute = AsyncMock(return_value=result)

        with pytest.raises(ForbiddenError):
            await get_assignment_analytics(db, teacher_b, assignment_id)

    @pytest.mark.asyncio
    async def test_score_distribution_is_sorted_by_score(self) -> None:
        """Raw score distribution is ordered by ascending score value."""
        from app.services.class_insights import get_assignment_analytics

        teacher_id = uuid.uuid4()
        assignment_id = uuid.uuid4()
        class_id = uuid.uuid4()
        crit_id = uuid.uuid4()

        snapshot = _snapshot_with_criteria([
            _make_criterion(str(crit_id), "Analysis", min_score=0, max_score=4),
        ])

        db = AsyncMock()
        ownership_row = _make_row(id=assignment_id, class_id=class_id, teacher_id=teacher_id)
        ownership_result = MagicMock()
        ownership_result.one_or_none.return_value = ownership_row
        assignment_obj = self._make_assignment_orm(assignment_id, class_id, snapshot)
        assignment_result = MagicMock()
        assignment_result.scalar_one.return_value = assignment_obj
        total_count_result = MagicMock()
        total_count_result.scalar_one.return_value = 3
        locked_count_result = MagicMock()
        locked_count_result.scalar_one.return_value = 3

        # Scores: 4, 2, 3 (out of order)
        score_rows = [
            _make_row(rubric_criterion_id=crit_id, final_score=4),
            _make_row(rubric_criterion_id=crit_id, final_score=2),
            _make_row(rubric_criterion_id=crit_id, final_score=3),
        ]
        scores_result = MagicMock()
        scores_result.all.return_value = score_rows

        db.execute = AsyncMock(
            side_effect=[
                ownership_result,
                assignment_result,
                total_count_result,
                locked_count_result,
                scores_result,
            ]
        )

        analytics = await get_assignment_analytics(db, teacher_id, assignment_id)

        dist = analytics.criterion_analytics[0].score_distribution
        score_values = [entry.score for entry in dist]
        assert score_values == sorted(score_values), "Distribution must be sorted by score."

    @pytest.mark.asyncio
    async def test_criteria_ordered_by_display_order(self) -> None:
        """Criteria appear in ascending display_order from the rubric snapshot."""
        from app.services.class_insights import get_assignment_analytics

        teacher_id = uuid.uuid4()
        assignment_id = uuid.uuid4()
        class_id = uuid.uuid4()
        crit_id_1 = uuid.uuid4()
        crit_id_2 = uuid.uuid4()

        snapshot = _snapshot_with_criteria([
            _make_criterion(str(crit_id_2), "Evidence Use", min_score=0, max_score=4, display_order=2),
            _make_criterion(str(crit_id_1), "Thesis Statement", min_score=0, max_score=4, display_order=1),
        ])

        db = AsyncMock()
        ownership_row = _make_row(id=assignment_id, class_id=class_id, teacher_id=teacher_id)
        ownership_result = MagicMock()
        ownership_result.one_or_none.return_value = ownership_row
        assignment_obj = self._make_assignment_orm(assignment_id, class_id, snapshot)
        assignment_result = MagicMock()
        assignment_result.scalar_one.return_value = assignment_obj
        total_count_result = MagicMock()
        total_count_result.scalar_one.return_value = 1
        locked_count_result = MagicMock()
        locked_count_result.scalar_one.return_value = 1
        scores_result = MagicMock()
        scores_result.all.return_value = []

        db.execute = AsyncMock(
            side_effect=[
                ownership_result,
                assignment_result,
                total_count_result,
                locked_count_result,
                scores_result,
            ]
        )

        analytics = await get_assignment_analytics(db, teacher_id, assignment_id)

        names = [c.criterion_name for c in analytics.criterion_analytics]
        assert names == ["Thesis Statement", "Evidence Use"]
