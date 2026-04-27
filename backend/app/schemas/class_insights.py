"""Pydantic schemas for the class insights and assignment analytics endpoints.

No student PII is collected, processed, or stored here.
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Shared sub-schemas
# ---------------------------------------------------------------------------


class ScoreBucket(BaseModel):
    """One histogram bucket for a score distribution."""

    label: str = Field(description="Human-readable bucket label, e.g. '0-20%'.")
    count: int = Field(ge=0)


class SkillAverage(BaseModel):
    """Aggregated statistics for one canonical skill dimension."""

    avg_score: float = Field(
        ge=0.0,
        le=1.0,
        description="Mean normalised score (0.0–1.0) across all contributing essays.",
    )
    student_count: int = Field(ge=0, description="Number of students with at least one score.")
    data_points: int = Field(ge=0, description="Total individual criterion scores contributing.")


class CommonIssue(BaseModel):
    """A skill dimension where the class average is below the concern threshold."""

    skill_dimension: str = Field(description="Canonical skill dimension name.")
    avg_score: float = Field(
        ge=0.0,
        le=1.0,
        description="Mean normalised score for this skill across the class.",
    )
    affected_student_count: int = Field(
        ge=0,
        description="Number of students whose per-skill average is below the concern threshold.",
    )


# ---------------------------------------------------------------------------
# Class insights response
# ---------------------------------------------------------------------------


class ClassInsightsResponse(BaseModel):
    """Response for GET /classes/{classId}/insights.

    Aggregates skill-level averages, score distributions, and common issues
    across all locked grades for all assignments in the class.
    """

    class_id: uuid.UUID
    assignment_count: int = Field(ge=0)
    student_count: int = Field(ge=0)
    graded_essay_count: int = Field(
        ge=0,
        description="Number of essays that have at least one locked grade.",
    )
    skill_averages: dict[str, SkillAverage] = Field(
        description="Per-skill aggregated averages keyed by canonical skill dimension name."
    )
    score_distributions: dict[str, list[ScoreBucket]] = Field(
        description=(
            "Per-skill score distribution across five 20-percentage-point buckets, "
            "keyed by canonical skill dimension name."
        )
    )
    common_issues: list[CommonIssue] = Field(
        description=(
            "Skill dimensions where the class average falls below the concern threshold "
            "(normalised score < 0.60), ranked by ascending average score."
        )
    )


# ---------------------------------------------------------------------------
# Assignment analytics sub-schemas
# ---------------------------------------------------------------------------


class ScoreCount(BaseModel):
    """A single (raw score value, count) pair in a per-criterion distribution."""

    score: int
    count: int = Field(ge=0)


class CriterionAnalytics(BaseModel):
    """Per-criterion analytics for one assignment."""

    criterion_id: uuid.UUID
    criterion_name: str
    skill_dimension: str = Field(description="Canonical skill dimension this criterion maps to.")
    min_score_possible: int = Field(description="Minimum score on the rubric for this criterion.")
    max_score_possible: int = Field(description="Maximum score on the rubric for this criterion.")
    avg_score: float = Field(description="Mean raw final_score across all locked essays.")
    avg_normalized_score: float = Field(
        ge=0.0,
        le=1.0,
        description="Mean normalised score (0.0–1.0) across all locked essays.",
    )
    score_distribution: list[ScoreCount] = Field(
        description="Count of essays per raw score value, ordered by ascending score."
    )


# ---------------------------------------------------------------------------
# Assignment analytics response
# ---------------------------------------------------------------------------


class AssignmentAnalyticsResponse(BaseModel):
    """Response for GET /assignments/{assignmentId}/analytics.

    Provides per-criterion score breakdowns and overall class performance
    for a single assignment.
    """

    assignment_id: uuid.UUID
    class_id: uuid.UUID
    total_essay_count: int = Field(ge=0, description="Total essays submitted for this assignment.")
    locked_essay_count: int = Field(
        ge=0,
        description="Essays with a locked grade (included in analytics).",
    )
    overall_avg_normalized_score: float | None = Field(
        default=None,
        description=(
            "Mean normalised score across all criteria and all locked essays. "
            "Null when there are no locked grades."
        ),
    )
    criterion_analytics: list[CriterionAnalytics] = Field(
        description="Per-criterion analytics in rubric display_order."
    )
