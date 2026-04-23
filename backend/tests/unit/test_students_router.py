"""Unit tests for student and enrollment endpoints.

Tests cover:
- GET  /api/v1/classes/{id}/students       — list enrolled, 404, 403, auth
- POST /api/v1/classes/{id}/students       — enroll new, enroll existing, 409, 404, 403, auth
- DELETE /api/v1/classes/{id}/students/{id} — soft-remove, 404, 403, auth
- GET  /api/v1/students/{id}               — get, 404, 403, auth
- PATCH /api/v1/students/{id}              — update, 404, 403, auth
- Cross-teacher access returns 403 (tenant isolation)

No real PostgreSQL.  All DB / service calls are mocked.  No student PII.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from app.dependencies import get_current_teacher
from app.exceptions import ConflictError, ForbiddenError, NotFoundError
from app.main import create_app

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_teacher(teacher_id: uuid.UUID | None = None) -> MagicMock:
    teacher = MagicMock()
    teacher.id = teacher_id or uuid.uuid4()
    teacher.email = "teacher@school.edu"
    teacher.email_verified = True
    return teacher


def _make_student_orm(
    teacher_id: uuid.UUID | None = None,
    student_id: uuid.UUID | None = None,
    full_name: str = "Student One",
    external_id: str | None = None,
) -> MagicMock:
    student = MagicMock()
    student.id = student_id or uuid.uuid4()
    student.teacher_id = teacher_id or uuid.uuid4()
    student.full_name = full_name
    student.external_id = external_id
    student.created_at = datetime.now(UTC)
    return student


def _make_enrollment_orm(
    class_id: uuid.UUID | None = None,
    student_id: uuid.UUID | None = None,
    enrollment_id: uuid.UUID | None = None,
    removed_at: datetime | None = None,
) -> MagicMock:
    enrollment = MagicMock()
    enrollment.id = enrollment_id or uuid.uuid4()
    enrollment.class_id = class_id or uuid.uuid4()
    enrollment.student_id = student_id or uuid.uuid4()
    enrollment.enrolled_at = datetime.now(UTC)
    enrollment.removed_at = removed_at
    return enrollment


def _app_with_teacher(teacher: MagicMock | None = None) -> object:
    teacher = teacher or _make_teacher()
    app = create_app()
    app.dependency_overrides[get_current_teacher] = lambda: teacher  # type: ignore[attr-defined]
    return app


# ---------------------------------------------------------------------------
# GET /api/v1/classes/{classId}/students
# ---------------------------------------------------------------------------


class TestListEnrolledStudents:
    def test_returns_empty_list(self) -> None:
        teacher = _make_teacher()
        class_id = uuid.uuid4()
        app = _app_with_teacher(teacher)
        with (
            patch(
                "app.routers.classes.list_enrolled_students",
                new_callable=AsyncMock,
                return_value=[],
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.get(f"/api/v1/classes/{class_id}/students")

        assert resp.status_code == 200, resp.text
        assert resp.json()["data"] == []

    def test_returns_enrolled_students(self) -> None:
        teacher = _make_teacher()
        class_id = uuid.uuid4()
        student = _make_student_orm(teacher_id=teacher.id)
        enrollment = _make_enrollment_orm(class_id=class_id, student_id=student.id)
        app = _app_with_teacher(teacher)
        with (
            patch(
                "app.routers.classes.list_enrolled_students",
                new_callable=AsyncMock,
                return_value=[(enrollment, student)],
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.get(f"/api/v1/classes/{class_id}/students")

        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert len(data) == 1
        assert data[0]["enrollment_id"] == str(enrollment.id)
        assert data[0]["student"]["id"] == str(student.id)

    def test_returns_404_when_class_not_found(self) -> None:
        teacher = _make_teacher()
        class_id = uuid.uuid4()
        app = _app_with_teacher(teacher)
        with (
            patch(
                "app.routers.classes.list_enrolled_students",
                new_callable=AsyncMock,
                side_effect=NotFoundError("Class not found."),
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.get(f"/api/v1/classes/{class_id}/students")

        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "NOT_FOUND"

    def test_returns_403_for_other_teachers_class(self) -> None:
        teacher = _make_teacher()
        class_id = uuid.uuid4()
        app = _app_with_teacher(teacher)
        with (
            patch(
                "app.routers.classes.list_enrolled_students",
                new_callable=AsyncMock,
                side_effect=ForbiddenError("You do not have access to this class."),
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.get(f"/api/v1/classes/{class_id}/students")

        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "FORBIDDEN"

    def test_requires_authentication(self) -> None:
        app = create_app()
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get(f"/api/v1/classes/{uuid.uuid4()}/students")
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "UNAUTHORIZED"


# ---------------------------------------------------------------------------
# POST /api/v1/classes/{classId}/students
# ---------------------------------------------------------------------------


class TestEnrollStudent:
    def test_creates_new_student_and_returns_201(self) -> None:
        teacher = _make_teacher()
        class_id = uuid.uuid4()
        student = _make_student_orm(teacher_id=teacher.id)
        enrollment = _make_enrollment_orm(class_id=class_id, student_id=student.id)
        app = _app_with_teacher(teacher)
        with (
            patch(
                "app.routers.classes.enroll_student",
                new_callable=AsyncMock,
                return_value=(enrollment, student),
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.post(
                f"/api/v1/classes/{class_id}/students",
                json={"full_name": "Student One"},
            )

        assert resp.status_code == 201, resp.text
        data = resp.json()["data"]
        assert data["enrollment_id"] == str(enrollment.id)
        assert data["student"]["id"] == str(student.id)

    def test_enrolls_existing_student(self) -> None:
        teacher = _make_teacher()
        class_id = uuid.uuid4()
        student_id = uuid.uuid4()
        student = _make_student_orm(teacher_id=teacher.id, student_id=student_id)
        enrollment = _make_enrollment_orm(class_id=class_id, student_id=student_id)
        app = _app_with_teacher(teacher)
        with (
            patch(
                "app.routers.classes.enroll_student",
                new_callable=AsyncMock,
                return_value=(enrollment, student),
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.post(
                f"/api/v1/classes/{class_id}/students",
                json={"student_id": str(student_id)},
            )

        assert resp.status_code == 201, resp.text
        assert resp.json()["data"]["student"]["id"] == str(student_id)

    def test_returns_422_when_no_identifier(self) -> None:
        app = _app_with_teacher()
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(
                f"/api/v1/classes/{uuid.uuid4()}/students",
                json={},
            )
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "VALIDATION_ERROR"

    def test_returns_422_when_both_student_id_and_full_name(self) -> None:
        app = _app_with_teacher()
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(
                f"/api/v1/classes/{uuid.uuid4()}/students",
                json={"student_id": str(uuid.uuid4()), "full_name": "Student One"},
            )
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "VALIDATION_ERROR"

    def test_returns_409_when_already_enrolled(self) -> None:
        teacher = _make_teacher()
        class_id = uuid.uuid4()
        app = _app_with_teacher(teacher)
        with (
            patch(
                "app.routers.classes.enroll_student",
                new_callable=AsyncMock,
                side_effect=ConflictError("Student is already enrolled in this class."),
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.post(
                f"/api/v1/classes/{class_id}/students",
                json={"full_name": "Student One"},
            )

        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "CONFLICT"

    def test_returns_404_when_class_not_found(self) -> None:
        teacher = _make_teacher()
        app = _app_with_teacher(teacher)
        with (
            patch(
                "app.routers.classes.enroll_student",
                new_callable=AsyncMock,
                side_effect=NotFoundError("Class not found."),
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.post(
                f"/api/v1/classes/{uuid.uuid4()}/students",
                json={"full_name": "Student One"},
            )

        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "NOT_FOUND"

    def test_returns_403_for_other_teachers_class(self) -> None:
        teacher = _make_teacher()
        app = _app_with_teacher(teacher)
        with (
            patch(
                "app.routers.classes.enroll_student",
                new_callable=AsyncMock,
                side_effect=ForbiddenError("You do not have access to this class."),
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.post(
                f"/api/v1/classes/{uuid.uuid4()}/students",
                json={"full_name": "Student One"},
            )

        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "FORBIDDEN"

    def test_requires_authentication(self) -> None:
        app = create_app()
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(
                f"/api/v1/classes/{uuid.uuid4()}/students",
                json={"full_name": "Student One"},
            )
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "UNAUTHORIZED"


# ---------------------------------------------------------------------------
# DELETE /api/v1/classes/{classId}/students/{studentId}
# ---------------------------------------------------------------------------


class TestRemoveEnrollment:
    def test_soft_removes_enrollment(self) -> None:
        teacher = _make_teacher()
        class_id = uuid.uuid4()
        student_id = uuid.uuid4()
        enrollment = _make_enrollment_orm(
            class_id=class_id,
            student_id=student_id,
            removed_at=datetime.now(UTC),
        )
        app = _app_with_teacher(teacher)
        with (
            patch(
                "app.routers.classes.remove_enrollment",
                new_callable=AsyncMock,
                return_value=enrollment,
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.delete(f"/api/v1/classes/{class_id}/students/{student_id}")

        assert resp.status_code == 204, resp.text

    def test_returns_404_when_enrollment_not_found(self) -> None:
        teacher = _make_teacher()
        app = _app_with_teacher(teacher)
        with (
            patch(
                "app.routers.classes.remove_enrollment",
                new_callable=AsyncMock,
                side_effect=NotFoundError("Active enrollment not found."),
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.delete(f"/api/v1/classes/{uuid.uuid4()}/students/{uuid.uuid4()}")

        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "NOT_FOUND"

    def test_returns_403_for_other_teachers_class(self) -> None:
        teacher = _make_teacher()
        app = _app_with_teacher(teacher)
        with (
            patch(
                "app.routers.classes.remove_enrollment",
                new_callable=AsyncMock,
                side_effect=ForbiddenError("You do not have access to this class."),
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.delete(f"/api/v1/classes/{uuid.uuid4()}/students/{uuid.uuid4()}")

        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "FORBIDDEN"

    def test_requires_authentication(self) -> None:
        app = create_app()
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.delete(f"/api/v1/classes/{uuid.uuid4()}/students/{uuid.uuid4()}")
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "UNAUTHORIZED"


# ---------------------------------------------------------------------------
# GET /api/v1/students/{studentId}
# ---------------------------------------------------------------------------


class TestGetStudent:
    def test_returns_student(self) -> None:
        teacher = _make_teacher()
        student = _make_student_orm(teacher_id=teacher.id)
        app = _app_with_teacher(teacher)
        with (
            patch(
                "app.routers.students.get_student",
                new_callable=AsyncMock,
                return_value=student,
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.get(f"/api/v1/students/{student.id}")

        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["id"] == str(student.id)

    def test_returns_404_when_not_found(self) -> None:
        teacher = _make_teacher()
        app = _app_with_teacher(teacher)
        with (
            patch(
                "app.routers.students.get_student",
                new_callable=AsyncMock,
                side_effect=NotFoundError("Student not found."),
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.get(f"/api/v1/students/{uuid.uuid4()}")

        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "NOT_FOUND"

    def test_returns_403_for_other_teachers_student(self) -> None:
        teacher = _make_teacher()
        app = _app_with_teacher(teacher)
        with (
            patch(
                "app.routers.students.get_student",
                new_callable=AsyncMock,
                side_effect=ForbiddenError("You do not have access to this student."),
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.get(f"/api/v1/students/{uuid.uuid4()}")

        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "FORBIDDEN"

    def test_requires_authentication(self) -> None:
        app = create_app()
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get(f"/api/v1/students/{uuid.uuid4()}")
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "UNAUTHORIZED"


# ---------------------------------------------------------------------------
# PATCH /api/v1/students/{studentId}
# ---------------------------------------------------------------------------


class TestPatchStudent:
    def test_updates_student_name(self) -> None:
        teacher = _make_teacher()
        student = _make_student_orm(teacher_id=teacher.id, full_name="Updated Name")
        app = _app_with_teacher(teacher)
        with (
            patch(
                "app.routers.students.update_student",
                new_callable=AsyncMock,
                return_value=student,
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.patch(
                f"/api/v1/students/{student.id}",
                json={"full_name": "Updated Name"},
            )

        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["full_name"] == "Updated Name"

    def test_returns_404_when_not_found(self) -> None:
        teacher = _make_teacher()
        app = _app_with_teacher(teacher)
        with (
            patch(
                "app.routers.students.update_student",
                new_callable=AsyncMock,
                side_effect=NotFoundError("Student not found."),
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.patch(
                f"/api/v1/students/{uuid.uuid4()}",
                json={"full_name": "Updated Name"},
            )

        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "NOT_FOUND"

    def test_returns_403_for_other_teachers_student(self) -> None:
        teacher = _make_teacher()
        app = _app_with_teacher(teacher)
        with (
            patch(
                "app.routers.students.update_student",
                new_callable=AsyncMock,
                side_effect=ForbiddenError("You do not have access to this student."),
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.patch(
                f"/api/v1/students/{uuid.uuid4()}",
                json={"full_name": "Updated Name"},
            )

        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "FORBIDDEN"

    def test_requires_authentication(self) -> None:
        app = create_app()
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.patch(
                f"/api/v1/students/{uuid.uuid4()}",
                json={"full_name": "Updated Name"},
            )
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "UNAUTHORIZED"


# ---------------------------------------------------------------------------
# Tenant isolation
# ---------------------------------------------------------------------------


class TestStudentTenantIsolation:
    def test_get_other_teacher_student_returns_403(self) -> None:
        """Attempting to GET another teacher's student returns 403."""
        teacher_b = _make_teacher()
        app = _app_with_teacher(teacher_b)
        with (
            patch(
                "app.routers.students.get_student",
                new_callable=AsyncMock,
                side_effect=ForbiddenError("You do not have access to this student."),
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.get(f"/api/v1/students/{uuid.uuid4()}")

        assert resp.status_code == 403, resp.text
        assert resp.json()["error"]["code"] == "FORBIDDEN"

    def test_enroll_in_other_teacher_class_returns_403(self) -> None:
        """Attempting to enroll in another teacher's class returns 403."""
        teacher_b = _make_teacher()
        app = _app_with_teacher(teacher_b)
        with (
            patch(
                "app.routers.classes.enroll_student",
                new_callable=AsyncMock,
                side_effect=ForbiddenError("You do not have access to this class."),
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.post(
                f"/api/v1/classes/{uuid.uuid4()}/students",
                json={"full_name": "Student One"},
            )

        assert resp.status_code == 403, resp.text
        assert resp.json()["error"]["code"] == "FORBIDDEN"

    def test_delete_enrollment_other_teacher_class_returns_403(self) -> None:
        """Attempting to soft-remove a student from another teacher's class returns 403."""
        teacher_b = _make_teacher()
        app = _app_with_teacher(teacher_b)
        with (
            patch(
                "app.routers.classes.remove_enrollment",
                new_callable=AsyncMock,
                side_effect=ForbiddenError("You do not have access to this class."),
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.delete(f"/api/v1/classes/{uuid.uuid4()}/students/{uuid.uuid4()}")

        assert resp.status_code == 403, resp.text
        assert resp.json()["error"]["code"] == "FORBIDDEN"
