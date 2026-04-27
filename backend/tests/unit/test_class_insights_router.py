"""Unit tests for the class insights router endpoints.

Tests cover:
- GET /api/v1/classes/{id}/insights      — returns insights, auth required, 403, 404
- GET /api/v1/assignments/{id}/analytics — returns analytics, auth required, 403, 404
- Tenant isolation: cross-teacher access returns 403 for both endpoints

No real database.  All DB / service calls are mocked.  No student PII.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from app.dependencies import get_current_teacher
from app.exceptions import ForbiddenError, NotFoundError
from app.main import create_app
from app.schemas.class_insights import (
    AssignmentAnalyticsResponse,
    ClassInsightsResponse,
    CommonIssue,
    CriterionAnalytics,
    ScoreBucket,
    ScoreCount,
    SkillAverage,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_teacher(teacher_id: uuid.UUID | None = None) -> MagicMock:
    teacher = MagicMock()
    teacher.id = teacher_id or uuid.uuid4()
    teacher.email = "teacher@school.edu"
    teacher.email_verified = True
    return teacher


def _app_with_teacher(teacher: MagicMock | None = None) -> object:
    teacher = teacher or _make_teacher()
    app = create_app()
    app.dependency_overrides[get_current_teacher] = lambda: teacher  # type: ignore[attr-defined]
    return app


def _make_class_insights(class_id: uuid.UUID) -> ClassInsightsResponse:
    return ClassInsightsResponse(
        class_id=class_id,
        assignment_count=2,
        student_count=25,
        graded_essay_count=20,
        skill_averages={
            "thesis": SkillAverage(avg_score=0.75, student_count=20, data_points=40),
            "evidence": SkillAverage(avg_score=0.55, student_count=20, data_points=40),
        },
        score_distributions={
            "thesis": [
                ScoreBucket(label="0-20%", count=1),
                ScoreBucket(label="20-40%", count=3),
                ScoreBucket(label="40-60%", count=6),
                ScoreBucket(label="60-80%", count=8),
                ScoreBucket(label="80-100%", count=2),
            ],
            "evidence": [
                ScoreBucket(label="0-20%", count=2),
                ScoreBucket(label="20-40%", count=5),
                ScoreBucket(label="40-60%", count=7),
                ScoreBucket(label="60-80%", count=5),
                ScoreBucket(label="80-100%", count=1),
            ],
        },
        common_issues=[
            CommonIssue(skill_dimension="evidence", avg_score=0.55, affected_student_count=12)
        ],
    )


def _make_assignment_analytics(
    assignment_id: uuid.UUID,
    class_id: uuid.UUID,
) -> AssignmentAnalyticsResponse:
    criterion_id = uuid.uuid4()
    return AssignmentAnalyticsResponse(
        assignment_id=assignment_id,
        class_id=class_id,
        total_essay_count=28,
        locked_essay_count=25,
        overall_avg_normalized_score=0.72,
        criterion_analytics=[
            CriterionAnalytics(
                criterion_id=criterion_id,
                criterion_name="Thesis Statement",
                skill_dimension="thesis",
                min_score_possible=0,
                max_score_possible=5,
                avg_score=3.6,
                avg_normalized_score=0.72,
                score_distribution=[
                    ScoreCount(score=3, count=10),
                    ScoreCount(score=4, count=8),
                    ScoreCount(score=5, count=7),
                ],
            )
        ],
    )


# ---------------------------------------------------------------------------
# GET /api/v1/classes/{classId}/insights
# ---------------------------------------------------------------------------


class TestGetClassInsights:
    def test_returns_insights(self) -> None:
        teacher = _make_teacher()
        class_id = uuid.uuid4()
        insights = _make_class_insights(class_id)
        app = _app_with_teacher(teacher)
        with (
            patch(
                "app.routers.classes.get_class_insights",
                new_callable=AsyncMock,
                return_value=insights,
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.get(f"/api/v1/classes/{class_id}/insights")

        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["class_id"] == str(class_id)
        assert data["assignment_count"] == 2
        assert data["student_count"] == 25
        assert data["graded_essay_count"] == 20
        assert "thesis" in data["skill_averages"]
        assert "evidence" in data["skill_averages"]
        assert data["skill_averages"]["thesis"]["avg_score"] == 0.75
        assert len(data["score_distributions"]["thesis"]) == 5
        assert len(data["common_issues"]) == 1
        assert data["common_issues"][0]["skill_dimension"] == "evidence"

    def test_returns_404_when_class_not_found(self) -> None:
        teacher = _make_teacher()
        class_id = uuid.uuid4()
        app = _app_with_teacher(teacher)
        with (
            patch(
                "app.routers.classes.get_class_insights",
                new_callable=AsyncMock,
                side_effect=NotFoundError("Class not found."),
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.get(f"/api/v1/classes/{class_id}/insights")

        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "NOT_FOUND"

    def test_returns_403_for_other_teachers_class(self) -> None:
        teacher = _make_teacher()
        class_id = uuid.uuid4()
        app = _app_with_teacher(teacher)
        with (
            patch(
                "app.routers.classes.get_class_insights",
                new_callable=AsyncMock,
                side_effect=ForbiddenError("You do not have access to this class."),
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.get(f"/api/v1/classes/{class_id}/insights")

        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "FORBIDDEN"

    def test_requires_authentication(self) -> None:
        app = create_app()
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get(f"/api/v1/classes/{uuid.uuid4()}/insights")
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "UNAUTHORIZED"

    def test_passes_teacher_id_to_service(self) -> None:
        """Router must forward the authenticated teacher's id to the service."""
        teacher = _make_teacher()
        class_id = uuid.uuid4()
        insights = _make_class_insights(class_id)
        app = _app_with_teacher(teacher)
        mock_service = AsyncMock(return_value=insights)
        with (
            patch("app.routers.classes.get_class_insights", mock_service),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            client.get(f"/api/v1/classes/{class_id}/insights")

        mock_service.assert_called_once()
        call_kwargs = mock_service.call_args
        # positional: db, teacher_id, class_id
        assert call_kwargs.args[1] == teacher.id
        assert call_kwargs.args[2] == class_id

    def test_empty_insights_returns_200(self) -> None:
        """A class with no graded essays returns a valid empty response."""
        teacher = _make_teacher()
        class_id = uuid.uuid4()
        empty_insights = ClassInsightsResponse(
            class_id=class_id,
            assignment_count=0,
            student_count=0,
            graded_essay_count=0,
            skill_averages={},
            score_distributions={},
            common_issues=[],
        )
        app = _app_with_teacher(teacher)
        with (
            patch(
                "app.routers.classes.get_class_insights",
                new_callable=AsyncMock,
                return_value=empty_insights,
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.get(f"/api/v1/classes/{class_id}/insights")

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["graded_essay_count"] == 0
        assert data["skill_averages"] == {}
        assert data["common_issues"] == []


# ---------------------------------------------------------------------------
# GET /api/v1/assignments/{assignmentId}/analytics
# ---------------------------------------------------------------------------


class TestGetAssignmentAnalytics:
    def test_returns_analytics(self) -> None:
        teacher = _make_teacher()
        assignment_id = uuid.uuid4()
        class_id = uuid.uuid4()
        analytics = _make_assignment_analytics(assignment_id, class_id)
        app = _app_with_teacher(teacher)
        with (
            patch(
                "app.routers.assignments.get_assignment_analytics",
                new_callable=AsyncMock,
                return_value=analytics,
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.get(f"/api/v1/assignments/{assignment_id}/analytics")

        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["assignment_id"] == str(assignment_id)
        assert data["class_id"] == str(class_id)
        assert data["total_essay_count"] == 28
        assert data["locked_essay_count"] == 25
        assert data["overall_avg_normalized_score"] == 0.72
        assert len(data["criterion_analytics"]) == 1
        crit = data["criterion_analytics"][0]
        assert crit["criterion_name"] == "Thesis Statement"
        assert crit["skill_dimension"] == "thesis"
        assert crit["avg_normalized_score"] == 0.72

    def test_returns_404_when_assignment_not_found(self) -> None:
        teacher = _make_teacher()
        assignment_id = uuid.uuid4()
        app = _app_with_teacher(teacher)
        with (
            patch(
                "app.routers.assignments.get_assignment_analytics",
                new_callable=AsyncMock,
                side_effect=NotFoundError("Assignment not found."),
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.get(f"/api/v1/assignments/{assignment_id}/analytics")

        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "NOT_FOUND"

    def test_returns_403_for_other_teachers_assignment(self) -> None:
        teacher = _make_teacher()
        assignment_id = uuid.uuid4()
        app = _app_with_teacher(teacher)
        with (
            patch(
                "app.routers.assignments.get_assignment_analytics",
                new_callable=AsyncMock,
                side_effect=ForbiddenError("You do not have access to this assignment."),
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.get(f"/api/v1/assignments/{assignment_id}/analytics")

        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "FORBIDDEN"

    def test_requires_authentication(self) -> None:
        app = create_app()
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get(f"/api/v1/assignments/{uuid.uuid4()}/analytics")
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "UNAUTHORIZED"

    def test_passes_teacher_id_to_service(self) -> None:
        """Router must forward the authenticated teacher's id to the service."""
        teacher = _make_teacher()
        assignment_id = uuid.uuid4()
        class_id = uuid.uuid4()
        analytics = _make_assignment_analytics(assignment_id, class_id)
        app = _app_with_teacher(teacher)
        mock_service = AsyncMock(return_value=analytics)
        with (
            patch("app.routers.assignments.get_assignment_analytics", mock_service),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            client.get(f"/api/v1/assignments/{assignment_id}/analytics")

        mock_service.assert_called_once()
        call_kwargs = mock_service.call_args
        assert call_kwargs.args[1] == teacher.id
        assert call_kwargs.args[2] == assignment_id

    def test_null_overall_avg_when_no_locked_grades(self) -> None:
        """When no grades are locked, overall_avg_normalized_score is null."""
        teacher = _make_teacher()
        assignment_id = uuid.uuid4()
        class_id = uuid.uuid4()
        empty_analytics = AssignmentAnalyticsResponse(
            assignment_id=assignment_id,
            class_id=class_id,
            total_essay_count=10,
            locked_essay_count=0,
            overall_avg_normalized_score=None,
            criterion_analytics=[],
        )
        app = _app_with_teacher(teacher)
        with (
            patch(
                "app.routers.assignments.get_assignment_analytics",
                new_callable=AsyncMock,
                return_value=empty_analytics,
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.get(f"/api/v1/assignments/{assignment_id}/analytics")

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["overall_avg_normalized_score"] is None
        assert data["criterion_analytics"] == []


# ---------------------------------------------------------------------------
# Tenant isolation
# ---------------------------------------------------------------------------


class TestClassInsightsTenantIsolation:
    def test_insights_passes_teacher_id_preventing_cross_tenant_access(self) -> None:
        """A teacher can only access insights for their own class."""
        teacher_a = _make_teacher()
        teacher_b = _make_teacher()
        class_id = uuid.uuid4()  # belongs to teacher_a
        app = _app_with_teacher(teacher_b)
        with (
            patch(
                "app.routers.classes.get_class_insights",
                new_callable=AsyncMock,
                side_effect=ForbiddenError("You do not have access to this class."),
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.get(f"/api/v1/classes/{class_id}/insights")

        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "FORBIDDEN"

    def test_analytics_passes_teacher_id_preventing_cross_tenant_access(self) -> None:
        """A teacher can only access analytics for their own assignment."""
        teacher_a = _make_teacher()
        teacher_b = _make_teacher()
        assignment_id = uuid.uuid4()  # belongs to teacher_a
        app = _app_with_teacher(teacher_b)
        with (
            patch(
                "app.routers.assignments.get_assignment_analytics",
                new_callable=AsyncMock,
                side_effect=ForbiddenError("You do not have access to this assignment."),
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.get(f"/api/v1/assignments/{assignment_id}/analytics")

        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "FORBIDDEN"
