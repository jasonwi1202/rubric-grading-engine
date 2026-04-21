"""Unit tests for the assignments router endpoints.

Tests cover:
- GET  /api/v1/assignments/{id}   — get, 404, 403, auth required
- PATCH /api/v1/assignments/{id}  — update, 422 invalid transition, 403, 404, auth required
- GET  /api/v1/classes/{id}/assignments  — list, 403, auth required
- POST /api/v1/classes/{id}/assignments  — create, 403, 404, 201, auth required
- Cross-teacher access returns 403 (tenant isolation)

No real PostgreSQL.  All DB / service calls are mocked.  No student PII.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from app.dependencies import get_current_teacher
from app.exceptions import ForbiddenError, InvalidStateTransitionError, NotFoundError
from app.main import create_app
from app.models.assignment import AssignmentStatus

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_teacher(teacher_id: uuid.UUID | None = None) -> MagicMock:
    teacher = MagicMock()
    teacher.id = teacher_id or uuid.uuid4()
    teacher.email = "teacher@school.edu"
    teacher.email_verified = True
    return teacher


def _make_assignment_orm(
    teacher_id: uuid.UUID | None = None,
    assignment_id: uuid.UUID | None = None,
    class_id: uuid.UUID | None = None,
    rubric_id: uuid.UUID | None = None,
    status: AssignmentStatus = AssignmentStatus.draft,
    title: str = "Test Assignment",
) -> MagicMock:
    a = MagicMock()
    a.id = assignment_id or uuid.uuid4()
    a.class_id = class_id or uuid.uuid4()
    a.rubric_id = rubric_id or uuid.uuid4()
    a.title = title
    a.prompt = None
    a.due_date = None
    a.status = status
    a.rubric_snapshot = {"id": str(a.rubric_id), "name": "Test Rubric", "criteria": []}
    a.resubmission_enabled = False
    a.resubmission_limit = None
    a.created_at = datetime.now(UTC)
    return a


def _app_with_teacher(teacher: MagicMock | None = None) -> object:
    teacher = teacher or _make_teacher()
    app = create_app()
    app.dependency_overrides[get_current_teacher] = lambda: teacher  # type: ignore[attr-defined]
    return app


# ---------------------------------------------------------------------------
# GET /api/v1/assignments/{assignmentId}
# ---------------------------------------------------------------------------


class TestGetAssignment:
    def test_returns_assignment(self) -> None:
        teacher = _make_teacher()
        assignment = _make_assignment_orm(class_id=uuid.uuid4())
        app = _app_with_teacher(teacher)
        with (
            patch(
                "app.routers.assignments.get_assignment",
                new_callable=AsyncMock,
                return_value=assignment,
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.get(f"/api/v1/assignments/{assignment.id}")

        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["id"] == str(assignment.id)
        assert data["title"] == "Test Assignment"
        assert data["status"] == "draft"
        assert "rubric_snapshot" in data

    def test_returns_404_when_not_found(self) -> None:
        teacher = _make_teacher()
        app = _app_with_teacher(teacher)
        with (
            patch(
                "app.routers.assignments.get_assignment",
                new_callable=AsyncMock,
                side_effect=NotFoundError("Assignment not found."),
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.get(f"/api/v1/assignments/{uuid.uuid4()}")

        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "NOT_FOUND"

    def test_returns_403_for_other_teachers_assignment(self) -> None:
        teacher = _make_teacher()
        app = _app_with_teacher(teacher)
        with (
            patch(
                "app.routers.assignments.get_assignment",
                new_callable=AsyncMock,
                side_effect=ForbiddenError("You do not have access to this assignment."),
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.get(f"/api/v1/assignments/{uuid.uuid4()}")

        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "FORBIDDEN"

    def test_requires_authentication(self) -> None:
        app = create_app()
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get(f"/api/v1/assignments/{uuid.uuid4()}")
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "UNAUTHORIZED"


# ---------------------------------------------------------------------------
# PATCH /api/v1/assignments/{assignmentId}
# ---------------------------------------------------------------------------


class TestPatchAssignment:
    def test_updates_title(self) -> None:
        teacher = _make_teacher()
        assignment = _make_assignment_orm(title="Updated Title")
        app = _app_with_teacher(teacher)
        with (
            patch(
                "app.routers.assignments.update_assignment",
                new_callable=AsyncMock,
                return_value=assignment,
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.patch(
                f"/api/v1/assignments/{assignment.id}",
                json={"title": "Updated Title"},
            )

        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["title"] == "Updated Title"

    def test_advances_status(self) -> None:
        teacher = _make_teacher()
        assignment = _make_assignment_orm(status=AssignmentStatus.open)
        app = _app_with_teacher(teacher)
        with (
            patch(
                "app.routers.assignments.update_assignment",
                new_callable=AsyncMock,
                return_value=assignment,
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.patch(
                f"/api/v1/assignments/{assignment.id}",
                json={"status": "open"},
            )

        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["status"] == "open"

    def test_returns_422_on_invalid_status_transition(self) -> None:
        teacher = _make_teacher()
        assignment_id = uuid.uuid4()
        app = _app_with_teacher(teacher)
        with (
            patch(
                "app.routers.assignments.update_assignment",
                new_callable=AsyncMock,
                side_effect=InvalidStateTransitionError(
                    "Cannot transition from 'draft' to 'grading'.",
                    field="status",
                ),
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.patch(
                f"/api/v1/assignments/{assignment_id}",
                json={"status": "grading"},
            )

        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "INVALID_STATE_TRANSITION"

    def test_returns_404_when_not_found(self) -> None:
        teacher = _make_teacher()
        app = _app_with_teacher(teacher)
        with (
            patch(
                "app.routers.assignments.update_assignment",
                new_callable=AsyncMock,
                side_effect=NotFoundError("Assignment not found."),
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.patch(f"/api/v1/assignments/{uuid.uuid4()}", json={"title": "X"})

        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "NOT_FOUND"

    def test_returns_403_for_other_teachers_assignment(self) -> None:
        teacher = _make_teacher()
        app = _app_with_teacher(teacher)
        with (
            patch(
                "app.routers.assignments.update_assignment",
                new_callable=AsyncMock,
                side_effect=ForbiddenError("You do not have access to this assignment."),
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.patch(f"/api/v1/assignments/{uuid.uuid4()}", json={"title": "X"})

        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "FORBIDDEN"

    def test_requires_authentication(self) -> None:
        app = create_app()
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.patch(f"/api/v1/assignments/{uuid.uuid4()}", json={"title": "X"})
        assert resp.status_code == 401

    def test_passes_only_provided_fields_to_service(self) -> None:
        """model_fields_set ensures only provided fields trigger service updates."""
        teacher = _make_teacher()
        assignment = _make_assignment_orm()
        app = _app_with_teacher(teacher)
        mock_update = AsyncMock(return_value=assignment)
        with (
            patch("app.routers.assignments.update_assignment", mock_update),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            client.patch(
                f"/api/v1/assignments/{assignment.id}",
                json={"title": "Only Title"},
            )

        call_kwargs = mock_update.call_args.kwargs
        # prompt was NOT in the body, so update_prompt must be False
        assert call_kwargs["update_prompt"] is False
        assert call_kwargs["update_due_date"] is False
        assert call_kwargs["title"] == "Only Title"


# ---------------------------------------------------------------------------
# GET /api/v1/classes/{classId}/assignments
# ---------------------------------------------------------------------------


class TestListAssignmentsInClass:
    def test_returns_assignment_list(self) -> None:
        teacher = _make_teacher()
        class_id = uuid.uuid4()
        a1 = _make_assignment_orm(class_id=class_id, title="Essay 1")
        a2 = _make_assignment_orm(class_id=class_id, title="Essay 2")
        app = _app_with_teacher(teacher)
        with (
            patch(
                "app.routers.classes.list_assignments",
                new_callable=AsyncMock,
                return_value=[a1, a2],
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.get(f"/api/v1/classes/{class_id}/assignments")

        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert len(data) == 2
        assert data[0]["title"] == "Essay 1"
        assert data[1]["title"] == "Essay 2"

    def test_returns_empty_list(self) -> None:
        teacher = _make_teacher()
        class_id = uuid.uuid4()
        app = _app_with_teacher(teacher)
        with (
            patch(
                "app.routers.classes.list_assignments",
                new_callable=AsyncMock,
                return_value=[],
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.get(f"/api/v1/classes/{class_id}/assignments")

        assert resp.status_code == 200, resp.text
        assert resp.json()["data"] == []

    def test_returns_403_for_other_teachers_class(self) -> None:
        teacher = _make_teacher()
        class_id = uuid.uuid4()
        app = _app_with_teacher(teacher)
        with (
            patch(
                "app.routers.classes.list_assignments",
                new_callable=AsyncMock,
                side_effect=ForbiddenError("You do not have access to this class."),
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.get(f"/api/v1/classes/{class_id}/assignments")

        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "FORBIDDEN"

    def test_requires_authentication(self) -> None:
        app = create_app()
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get(f"/api/v1/classes/{uuid.uuid4()}/assignments")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# POST /api/v1/classes/{classId}/assignments
# ---------------------------------------------------------------------------


class TestCreateAssignmentInClass:
    def test_creates_assignment_returns_201(self) -> None:
        teacher = _make_teacher()
        class_id = uuid.uuid4()
        rubric_id = uuid.uuid4()
        assignment = _make_assignment_orm(
            class_id=class_id,
            rubric_id=rubric_id,
            title="New Assignment",
        )
        app = _app_with_teacher(teacher)
        with (
            patch(
                "app.routers.classes.create_assignment",
                new_callable=AsyncMock,
                return_value=assignment,
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.post(
                f"/api/v1/classes/{class_id}/assignments",
                json={
                    "rubric_id": str(rubric_id),
                    "title": "New Assignment",
                },
            )

        assert resp.status_code == 201, resp.text
        data = resp.json()["data"]
        assert data["title"] == "New Assignment"
        assert data["status"] == "draft"
        assert "rubric_snapshot" in data

    def test_rubric_snapshot_present_in_response(self) -> None:
        """Response always includes the immutable rubric_snapshot."""
        teacher = _make_teacher()
        class_id = uuid.uuid4()
        rubric_id = uuid.uuid4()
        assignment = _make_assignment_orm(class_id=class_id, rubric_id=rubric_id)
        assignment.rubric_snapshot = {
            "id": str(rubric_id),
            "name": "Writing Rubric",
            "description": None,
            "criteria": [],
        }
        app = _app_with_teacher(teacher)
        with (
            patch(
                "app.routers.classes.create_assignment",
                new_callable=AsyncMock,
                return_value=assignment,
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.post(
                f"/api/v1/classes/{class_id}/assignments",
                json={"rubric_id": str(rubric_id), "title": "Test"},
            )

        assert resp.status_code == 201
        assert resp.json()["data"]["rubric_snapshot"]["name"] == "Writing Rubric"

    def test_returns_404_when_class_not_found(self) -> None:
        teacher = _make_teacher()
        app = _app_with_teacher(teacher)
        with (
            patch(
                "app.routers.classes.create_assignment",
                new_callable=AsyncMock,
                side_effect=NotFoundError("Class not found."),
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.post(
                f"/api/v1/classes/{uuid.uuid4()}/assignments",
                json={"rubric_id": str(uuid.uuid4()), "title": "Test"},
            )

        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "NOT_FOUND"

    def test_returns_403_for_other_teachers_class(self) -> None:
        teacher = _make_teacher()
        app = _app_with_teacher(teacher)
        with (
            patch(
                "app.routers.classes.create_assignment",
                new_callable=AsyncMock,
                side_effect=ForbiddenError("You do not have access to this class."),
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.post(
                f"/api/v1/classes/{uuid.uuid4()}/assignments",
                json={"rubric_id": str(uuid.uuid4()), "title": "Test"},
            )

        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "FORBIDDEN"

    def test_returns_422_when_title_missing(self) -> None:
        app = _app_with_teacher()
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(
                f"/api/v1/classes/{uuid.uuid4()}/assignments",
                json={"rubric_id": str(uuid.uuid4())},
            )
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "VALIDATION_ERROR"

    def test_returns_422_when_rubric_id_missing(self) -> None:
        app = _app_with_teacher()
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(
                f"/api/v1/classes/{uuid.uuid4()}/assignments",
                json={"title": "Test"},
            )
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "VALIDATION_ERROR"

    def test_requires_authentication(self) -> None:
        app = create_app()
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(
                f"/api/v1/classes/{uuid.uuid4()}/assignments",
                json={"rubric_id": str(uuid.uuid4()), "title": "Test"},
            )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Tenant isolation
# ---------------------------------------------------------------------------


class TestAssignmentTenantIsolation:
    def test_get_uses_authenticated_teacher_id(self) -> None:
        teacher = _make_teacher()
        assignment = _make_assignment_orm()
        app = _app_with_teacher(teacher)
        mock_get = AsyncMock(return_value=assignment)
        with (
            patch("app.routers.assignments.get_assignment", mock_get),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            client.get(f"/api/v1/assignments/{assignment.id}")

        mock_get.assert_called_once()
        assert mock_get.call_args.args[1] == teacher.id

    def test_patch_uses_authenticated_teacher_id(self) -> None:
        teacher = _make_teacher()
        assignment = _make_assignment_orm()
        app = _app_with_teacher(teacher)
        mock_update = AsyncMock(return_value=assignment)
        with (
            patch("app.routers.assignments.update_assignment", mock_update),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            client.patch(f"/api/v1/assignments/{assignment.id}", json={"title": "T"})

        mock_update.assert_called_once()
        assert mock_update.call_args.kwargs["teacher_id"] == teacher.id

    def test_list_uses_authenticated_teacher_id(self) -> None:
        teacher = _make_teacher()
        class_id = uuid.uuid4()
        app = _app_with_teacher(teacher)
        mock_list = AsyncMock(return_value=[])
        with (
            patch("app.routers.classes.list_assignments", mock_list),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            client.get(f"/api/v1/classes/{class_id}/assignments")

        mock_list.assert_called_once()
        assert mock_list.call_args.kwargs["teacher_id"] == teacher.id

    def test_create_uses_authenticated_teacher_id(self) -> None:
        teacher = _make_teacher()
        class_id = uuid.uuid4()
        rubric_id = uuid.uuid4()
        assignment = _make_assignment_orm(class_id=class_id, rubric_id=rubric_id)
        app = _app_with_teacher(teacher)
        mock_create = AsyncMock(return_value=assignment)
        with (
            patch("app.routers.classes.create_assignment", mock_create),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            client.post(
                f"/api/v1/classes/{class_id}/assignments",
                json={"rubric_id": str(rubric_id), "title": "T"},
            )

        mock_create.assert_called_once()
        assert mock_create.call_args.kwargs["teacher_id"] == teacher.id
