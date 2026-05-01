"""Unit tests for cross-tenant access control (tenant isolation).

Verifies that every major resource type returns HTTP 403 — not 200 or 404 —
when teacher B attempts to access a resource that belongs to teacher A.

The tests work by:
1. Overriding ``get_current_teacher`` to inject teacher B's identity.
2. Patching the relevant service function to raise ``ForbiddenError`` (which
   is the correct service-layer response when ``teacher_id`` doesn't match).
3. Asserting the HTTP response code is 403 and the error code is "FORBIDDEN".

No real database or Redis is required — all external dependencies are mocked.
No student PII appears in any fixture or assertion.

Scope: these are **unit tests** that validate the exception-to-HTTP mapping
(i.e. that ``ForbiddenError`` from the service layer is correctly surfaced as
HTTP 403 with ``FORBIDDEN`` code through the router/exception-handler chain).
They do NOT exercise real database query scoping or PostgreSQL RLS behaviour.
Integration tests that verify actual tenant isolation end-to-end (creating
Teacher A resources in a real DB, authenticating as Teacher B, and asserting
zero-row / 403 responses) are tracked separately and require testcontainers.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.dependencies import get_current_teacher
from app.exceptions import ForbiddenError, NotFoundError
from app.main import create_app

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


def _make_teacher(teacher_id: uuid.UUID | None = None) -> MagicMock:
    teacher = MagicMock()
    teacher.id = teacher_id or uuid.uuid4()
    teacher.email = "teacher@school.edu"
    teacher.email_verified = True
    return teacher


def _app_with_teacher(teacher: MagicMock) -> FastAPI:
    """Return a FastAPI app whose ``get_current_teacher`` always returns *teacher*."""
    app = create_app()
    app.dependency_overrides[get_current_teacher] = lambda: teacher
    return app


def _assert_403(resp: httpx.Response) -> None:
    """Assert that the response carries HTTP 403 with the FORBIDDEN error code."""
    assert resp.status_code == 403, f"Expected 403, got {resp.status_code}: {resp.text}"
    body = resp.json()
    assert body.get("error", {}).get("code") == "FORBIDDEN", f"Unexpected body: {body}"


def _assert_404(resp: httpx.Response) -> None:
    """Assert that the response carries HTTP 404 with the NOT_FOUND error code."""
    assert resp.status_code == 404, f"Expected 404, got {resp.status_code}: {resp.text}"
    body = resp.json()
    assert body.get("error", {}).get("code") == "NOT_FOUND", f"Unexpected body: {body}"


# ---------------------------------------------------------------------------
# Classes — GET /api/v1/classes/{classId}
# ---------------------------------------------------------------------------


class TestClassTenantIsolation:
    def test_get_class_returns_403_for_another_teachers_class(self) -> None:
        teacher_b = _make_teacher()
        other_class_id = uuid.uuid4()
        app = _app_with_teacher(teacher_b)

        with (
            patch(
                "app.routers.classes.get_class",
                new_callable=AsyncMock,
                side_effect=ForbiddenError("class not accessible"),
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.get(f"/api/v1/classes/{other_class_id}")

        _assert_403(resp)

    def test_patch_class_returns_403_for_another_teachers_class(self) -> None:
        teacher_b = _make_teacher()
        other_class_id = uuid.uuid4()
        app = _app_with_teacher(teacher_b)

        with (
            patch(
                "app.routers.classes.update_class",
                new_callable=AsyncMock,
                side_effect=ForbiddenError("class not accessible"),
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.patch(
                f"/api/v1/classes/{other_class_id}",
                json={"name": "Hacked Class"},
            )

        _assert_403(resp)

    def test_archive_class_returns_403_for_another_teachers_class(self) -> None:
        teacher_b = _make_teacher()
        other_class_id = uuid.uuid4()
        app = _app_with_teacher(teacher_b)

        with (
            patch(
                "app.routers.classes.archive_class",
                new_callable=AsyncMock,
                side_effect=ForbiddenError("class not accessible"),
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.post(f"/api/v1/classes/{other_class_id}/archive")

        _assert_403(resp)


# ---------------------------------------------------------------------------
# Students — GET /api/v1/students/{studentId}
# ---------------------------------------------------------------------------


class TestStudentTenantIsolation:
    def test_get_student_returns_403_for_another_teachers_student(self) -> None:
        teacher_b = _make_teacher()
        other_student_id = uuid.uuid4()
        app = _app_with_teacher(teacher_b)

        with (
            patch(
                "app.routers.students.get_student_with_profile",
                new_callable=AsyncMock,
                side_effect=ForbiddenError("student not accessible"),
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.get(f"/api/v1/students/{other_student_id}")

        _assert_403(resp)

    def test_patch_student_returns_403_for_another_teachers_student(self) -> None:
        teacher_b = _make_teacher()
        other_student_id = uuid.uuid4()
        app = _app_with_teacher(teacher_b)

        with (
            patch(
                "app.routers.students.update_student",
                new_callable=AsyncMock,
                side_effect=ForbiddenError("student not accessible"),
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.patch(
                f"/api/v1/students/{other_student_id}",
                json={"full_name": "Hacked Name"},
            )

        _assert_403(resp)


# ---------------------------------------------------------------------------
# Rubrics — GET /api/v1/rubrics/{rubricId}
# ---------------------------------------------------------------------------


class TestRubricTenantIsolation:
    def test_get_rubric_returns_403_for_another_teachers_rubric(self) -> None:
        teacher_b = _make_teacher()
        other_rubric_id = uuid.uuid4()
        app = _app_with_teacher(teacher_b)

        with (
            patch(
                "app.routers.rubrics.get_rubric",
                new_callable=AsyncMock,
                side_effect=ForbiddenError("rubric not accessible"),
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.get(f"/api/v1/rubrics/{other_rubric_id}")

        _assert_403(resp)

    def test_patch_rubric_returns_403_for_another_teachers_rubric(self) -> None:
        teacher_b = _make_teacher()
        other_rubric_id = uuid.uuid4()
        app = _app_with_teacher(teacher_b)

        with (
            patch(
                "app.routers.rubrics.update_rubric",
                new_callable=AsyncMock,
                side_effect=ForbiddenError("rubric not accessible"),
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.patch(
                f"/api/v1/rubrics/{other_rubric_id}",
                json={"name": "Hacked Rubric"},
            )

        _assert_403(resp)

    def test_delete_rubric_returns_403_for_another_teachers_rubric(self) -> None:
        teacher_b = _make_teacher()
        other_rubric_id = uuid.uuid4()
        app = _app_with_teacher(teacher_b)

        with (
            patch(
                "app.routers.rubrics.delete_rubric",
                new_callable=AsyncMock,
                side_effect=ForbiddenError("rubric not accessible"),
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.delete(f"/api/v1/rubrics/{other_rubric_id}")

        _assert_403(resp)


# ---------------------------------------------------------------------------
# Assignments — GET /api/v1/assignments/{assignmentId}
# ---------------------------------------------------------------------------


class TestAssignmentTenantIsolation:
    def test_get_assignment_returns_403_for_another_teachers_assignment(self) -> None:
        teacher_b = _make_teacher()
        other_assignment_id = uuid.uuid4()
        app = _app_with_teacher(teacher_b)

        with (
            patch(
                "app.routers.assignments.get_assignment",
                new_callable=AsyncMock,
                side_effect=ForbiddenError("assignment not accessible"),
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.get(f"/api/v1/assignments/{other_assignment_id}")

        _assert_403(resp)

    def test_patch_assignment_returns_403_for_another_teachers_assignment(self) -> None:
        teacher_b = _make_teacher()
        other_assignment_id = uuid.uuid4()
        app = _app_with_teacher(teacher_b)

        with (
            patch(
                "app.routers.assignments.update_assignment",
                new_callable=AsyncMock,
                side_effect=ForbiddenError("assignment not accessible"),
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.patch(
                f"/api/v1/assignments/{other_assignment_id}",
                json={"title": "Hacked Assignment"},
            )

        _assert_403(resp)


# ---------------------------------------------------------------------------
# Essays — GET /api/v1/assignments/{assignmentId}/essays
# ---------------------------------------------------------------------------


class TestEssayTenantIsolation:
    def test_list_essays_returns_403_for_another_teachers_assignment(self) -> None:
        teacher_b = _make_teacher()
        other_assignment_id = uuid.uuid4()
        app = _app_with_teacher(teacher_b)

        with (
            patch(
                "app.routers.essays.list_essays_for_assignment",
                new_callable=AsyncMock,
                side_effect=ForbiddenError("assignment not accessible"),
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.get(f"/api/v1/assignments/{other_assignment_id}/essays")

        _assert_403(resp)


# ---------------------------------------------------------------------------
# Grades — GET /api/v1/essays/{essayId}/grade
# ---------------------------------------------------------------------------


class TestGradeTenantIsolation:
    def test_get_grade_returns_403_for_another_teachers_essay(self) -> None:
        teacher_b = _make_teacher()
        other_essay_id = uuid.uuid4()
        app = _app_with_teacher(teacher_b)

        with (
            patch(
                "app.routers.grades.get_grade_for_essay",
                new_callable=AsyncMock,
                side_effect=ForbiddenError("essay not accessible"),
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.get(f"/api/v1/essays/{other_essay_id}/grade")

        _assert_403(resp)

    def test_lock_grade_returns_403_for_another_teachers_grade(self) -> None:
        teacher_b = _make_teacher()
        other_grade_id = uuid.uuid4()
        app = _app_with_teacher(teacher_b)

        with (
            patch(
                "app.routers.grades.lock_grade",
                new_callable=AsyncMock,
                side_effect=ForbiddenError("grade not accessible"),
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.post(f"/api/v1/grades/{other_grade_id}/lock")

        _assert_403(resp)

    def test_patch_grade_feedback_returns_403_for_another_teachers_grade(self) -> None:
        teacher_b = _make_teacher()
        other_grade_id = uuid.uuid4()
        app = _app_with_teacher(teacher_b)

        with (
            patch(
                "app.routers.grades.update_grade_feedback",
                new_callable=AsyncMock,
                side_effect=ForbiddenError("grade not accessible"),
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.patch(
                f"/api/v1/grades/{other_grade_id}/feedback",
                json={"summary_feedback": "Hacked feedback"},
            )

        _assert_403(resp)


# ---------------------------------------------------------------------------
# Worklist — complete / snooze / dismiss
# ---------------------------------------------------------------------------


class TestWorklistTenantIsolation:
    def test_complete_worklist_item_returns_403_for_another_teachers_item(self) -> None:
        teacher_b = _make_teacher()
        other_item_id = uuid.uuid4()
        app = _app_with_teacher(teacher_b)

        with (
            patch(
                "app.routers.worklist.complete_worklist_item",
                new_callable=AsyncMock,
                side_effect=ForbiddenError("worklist item not accessible"),
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.post(f"/api/v1/worklist/{other_item_id}/complete")

        _assert_403(resp)

    def test_snooze_worklist_item_returns_403_for_another_teachers_item(self) -> None:
        teacher_b = _make_teacher()
        other_item_id = uuid.uuid4()
        app = _app_with_teacher(teacher_b)

        with (
            patch(
                "app.routers.worklist.snooze_worklist_item",
                new_callable=AsyncMock,
                side_effect=ForbiddenError("worklist item not accessible"),
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.post(f"/api/v1/worklist/{other_item_id}/snooze", json={})

        _assert_403(resp)

    def test_dismiss_worklist_item_returns_403_for_another_teachers_item(self) -> None:
        teacher_b = _make_teacher()
        other_item_id = uuid.uuid4()
        app = _app_with_teacher(teacher_b)

        with (
            patch(
                "app.routers.worklist.dismiss_worklist_item",
                new_callable=AsyncMock,
                side_effect=ForbiddenError("worklist item not accessible"),
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.delete(f"/api/v1/worklist/{other_item_id}")

        _assert_403(resp)


# ---------------------------------------------------------------------------
# Student Groups — GET /api/v1/classes/{classId}/groups
#                  PATCH /api/v1/classes/{classId}/groups/{groupId}
# ---------------------------------------------------------------------------


class TestStudentGroupTenantIsolation:
    def test_get_groups_returns_403_for_another_teachers_class(self) -> None:
        teacher_b = _make_teacher()
        other_class_id = uuid.uuid4()
        app = _app_with_teacher(teacher_b)

        with (
            patch(
                "app.routers.classes.list_class_groups",
                new_callable=AsyncMock,
                side_effect=ForbiddenError("class not accessible"),
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.get(f"/api/v1/classes/{other_class_id}/groups")

        _assert_403(resp)

    def test_patch_group_returns_403_for_another_teachers_class(self) -> None:
        teacher_b = _make_teacher()
        other_class_id = uuid.uuid4()
        other_group_id = uuid.uuid4()
        app = _app_with_teacher(teacher_b)

        with (
            patch(
                "app.routers.classes.update_group_members",
                new_callable=AsyncMock,
                side_effect=ForbiddenError("class not accessible"),
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.patch(
                f"/api/v1/classes/{other_class_id}/groups/{other_group_id}",
                json={"student_ids": []},
            )

        _assert_403(resp)


# ---------------------------------------------------------------------------
# Recommendations — POST /api/v1/recommendations/{id}/assign
#                   POST /api/v1/recommendations/{id}/dismiss
# ---------------------------------------------------------------------------


class TestRecommendationTenantIsolation:
    """Cross-tenant isolation tests for the recommendations endpoints.

    The recommendations service uses a single ``SELECT … WHERE id = ? AND
    teacher_id = ?`` query pattern (matching the FORCE RLS visibility model).
    Cross-tenant and nonexistent IDs are indistinguishable and both raise
    :exc:`~app.exceptions.NotFoundError`, which surfaces as HTTP 404
    (not 403 — this differs from most other resource types).
    """

    def test_assign_recommendation_returns_404_for_another_teachers_recommendation(
        self,
    ) -> None:
        teacher_b = _make_teacher()
        other_rec_id = uuid.uuid4()
        app = _app_with_teacher(teacher_b)

        with (
            patch(
                "app.routers.recommendations.assign_recommendation",
                new_callable=AsyncMock,
                side_effect=NotFoundError("Instruction recommendation not found."),
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.post(f"/api/v1/recommendations/{other_rec_id}/assign")

        _assert_404(resp)

    def test_dismiss_recommendation_returns_404_for_another_teachers_recommendation(
        self,
    ) -> None:
        teacher_b = _make_teacher()
        other_rec_id = uuid.uuid4()
        app = _app_with_teacher(teacher_b)

        with (
            patch(
                "app.routers.recommendations.dismiss_recommendation",
                new_callable=AsyncMock,
                side_effect=NotFoundError("Instruction recommendation not found."),
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.post(f"/api/v1/recommendations/{other_rec_id}/dismiss")

        _assert_404(resp)
