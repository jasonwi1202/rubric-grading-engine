"""Unit tests for instruction recommendation router endpoints (M6-07).

Tests cover HTTP layer concerns — status codes, response envelope shape,
exception-to-HTTP mapping, auth enforcement, and cross-teacher 403 isolation.
All service calls are mocked; no real DB or LLM is used.
No student PII in fixtures.

Endpoints under test:
  POST /api/v1/students/{studentId}/recommendations   — generate for student profile
  GET  /api/v1/students/{studentId}/recommendations   — list persisted recs
  POST /api/v1/classes/{classId}/groups/{groupId}/recommendations — generate for group
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from app.dependencies import get_current_teacher
from app.exceptions import ForbiddenError, LLMError, NotFoundError, ValidationError
from app.main import create_app

# ---------------------------------------------------------------------------
# Helpers / factories (no PII)
# ---------------------------------------------------------------------------


def _make_teacher(teacher_id: uuid.UUID | None = None) -> MagicMock:
    teacher = MagicMock()
    teacher.id = teacher_id or uuid.uuid4()
    teacher.email = "teacher@school.edu"
    teacher.email_verified = True
    return teacher


def _make_recommendation_orm(
    rec_id: uuid.UUID | None = None,
    teacher_id: uuid.UUID | None = None,
    student_id: uuid.UUID | None = None,
    group_id: uuid.UUID | None = None,
    skill_key: str | None = "evidence",
    grade_level: str = "Grade 8",
    status: str = "pending_review",
) -> MagicMock:
    """Build a minimal mock InstructionRecommendation ORM row — no PII."""
    rec = MagicMock()
    rec.id = rec_id or uuid.uuid4()
    rec.teacher_id = teacher_id or uuid.uuid4()
    rec.student_id = student_id
    rec.group_id = group_id
    rec.worklist_item_id = None
    rec.skill_key = skill_key
    rec.grade_level = grade_level
    rec.prompt_version = "instruction-v1"
    rec.recommendations = [
        {
            "skill_dimension": "evidence",
            "title": "Evidence Workshop",
            "description": "Practice integrating evidence.",
            "estimated_minutes": 20,
            "strategy_type": "guided_practice",
        }
    ]
    rec.evidence_summary = "Skill gap in 'evidence': average score 40%, trend stable."
    rec.status = status
    rec.created_at = datetime(2026, 4, 30, 0, 0, 0, tzinfo=UTC)
    return rec


def _client(teacher: MagicMock) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_current_teacher] = lambda: teacher
    return TestClient(app, raise_server_exceptions=False)


def _anon_client() -> TestClient:
    return TestClient(create_app(), raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# POST /api/v1/students/{studentId}/recommendations
# ---------------------------------------------------------------------------


class TestGenerateStudentRecommendationsEndpoint:
    _path = "/api/v1/students/{student_id}/recommendations"

    def _url(self, student_id: uuid.UUID | None = None) -> str:
        return self._path.format(student_id=student_id or uuid.uuid4())

    def _payload(self, **overrides) -> dict:
        base = {"grade_level": "Grade 8", "duration_minutes": 20}
        return {**base, **overrides}

    def test_happy_path_returns_201_with_envelope(self):
        teacher = _make_teacher()
        student_id = uuid.uuid4()
        rec = _make_recommendation_orm(teacher_id=teacher.id, student_id=student_id)
        with patch(
            "app.routers.students.generate_student_recommendations",
            new_callable=AsyncMock,
            return_value=rec,
        ):
            resp = _client(teacher).post(self._url(student_id), json=self._payload())
        assert resp.status_code == 201
        body = resp.json()
        assert "data" in body
        data = body["data"]
        assert data["grade_level"] == "Grade 8"
        assert data["status"] == "pending_review"
        assert len(data["recommendations"]) == 1
        assert data["recommendations"][0]["skill_dimension"] == "evidence"

    def test_optional_skill_key_is_forwarded(self):
        teacher = _make_teacher()
        student_id = uuid.uuid4()
        rec = _make_recommendation_orm(
            teacher_id=teacher.id, student_id=student_id, skill_key="thesis"
        )
        captured: list = []

        async def mock_generate(db, teacher_id, student_id_arg, **kwargs):
            captured.append(kwargs)
            return rec

        with patch(
            "app.routers.students.generate_student_recommendations", side_effect=mock_generate
        ):
            resp = _client(teacher).post(
                self._url(student_id),
                json=self._payload(skill_key="thesis"),
            )
        assert resp.status_code == 201
        assert captured[0]["skill_key"] == "thesis"

    def test_optional_worklist_item_id_is_forwarded(self):
        teacher = _make_teacher()
        student_id = uuid.uuid4()
        worklist_item_id = uuid.uuid4()
        rec = _make_recommendation_orm(teacher_id=teacher.id, student_id=student_id)
        captured: list = []

        async def mock_generate(db, teacher_id, student_id_arg, **kwargs):
            captured.append(kwargs)
            return rec

        with patch(
            "app.routers.students.generate_student_recommendations", side_effect=mock_generate
        ):
            resp = _client(teacher).post(
                self._url(student_id),
                json=self._payload(worklist_item_id=str(worklist_item_id)),
            )
        assert resp.status_code == 201
        assert captured[0]["worklist_item_id"] == worklist_item_id

    def test_student_not_found_returns_404(self):
        teacher = _make_teacher()
        with patch(
            "app.routers.students.generate_student_recommendations",
            new_callable=AsyncMock,
            side_effect=NotFoundError("Student not found."),
        ):
            resp = _client(teacher).post(self._url(), json=self._payload())
        assert resp.status_code == 404

    def test_forbidden_returns_403(self):
        teacher = _make_teacher()
        with patch(
            "app.routers.students.generate_student_recommendations",
            new_callable=AsyncMock,
            side_effect=ForbiddenError("You do not have access to this student."),
        ):
            resp = _client(teacher).post(self._url(), json=self._payload())
        assert resp.status_code == 403

    def test_no_profile_data_returns_422(self):
        teacher = _make_teacher()
        with patch(
            "app.routers.students.generate_student_recommendations",
            new_callable=AsyncMock,
            side_effect=ValidationError("No skill profile data.", field="student_id"),
        ):
            resp = _client(teacher).post(self._url(), json=self._payload())
        assert resp.status_code == 422

    def test_llm_service_unavailable_returns_503(self):
        teacher = _make_teacher()
        with patch(
            "app.routers.students.generate_student_recommendations",
            new_callable=AsyncMock,
            side_effect=LLMError("LLM unavailable"),
        ):
            resp = _client(teacher).post(self._url(), json=self._payload())
        assert resp.status_code == 503

    def test_unauthenticated_returns_401(self):
        resp = _anon_client().post(self._url(), json=self._payload())
        assert resp.status_code == 401

    def test_invalid_duration_returns_422(self):
        """duration_minutes must be between 5 and 120."""
        teacher = _make_teacher()
        resp = _client(teacher).post(
            self._url(), json={"grade_level": "Grade 8", "duration_minutes": 2}
        )
        assert resp.status_code == 422

    def test_missing_grade_level_returns_422(self):
        teacher = _make_teacher()
        resp = _client(teacher).post(self._url(), json={"duration_minutes": 20})
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET /api/v1/students/{studentId}/recommendations
# ---------------------------------------------------------------------------


class TestListStudentRecommendationsEndpoint:
    _path = "/api/v1/students/{student_id}/recommendations"

    def _url(self, student_id: uuid.UUID | None = None) -> str:
        return self._path.format(student_id=student_id or uuid.uuid4())

    def test_returns_200_with_list(self):
        teacher = _make_teacher()
        student_id = uuid.uuid4()
        rec = _make_recommendation_orm(teacher_id=teacher.id, student_id=student_id)
        with patch(
            "app.routers.students.list_student_recommendations",
            new_callable=AsyncMock,
            return_value=[rec],
        ):
            resp = _client(teacher).get(self._url(student_id))
        assert resp.status_code == 200
        body = resp.json()
        assert "data" in body
        assert isinstance(body["data"], list)
        assert len(body["data"]) == 1

    def test_returns_empty_list_when_no_recs(self):
        teacher = _make_teacher()
        with patch(
            "app.routers.students.list_student_recommendations",
            new_callable=AsyncMock,
            return_value=[],
        ):
            resp = _client(teacher).get(self._url())
        assert resp.status_code == 200
        assert resp.json()["data"] == []

    def test_student_not_found_returns_404(self):
        teacher = _make_teacher()
        with patch(
            "app.routers.students.list_student_recommendations",
            new_callable=AsyncMock,
            side_effect=NotFoundError("Student not found."),
        ):
            resp = _client(teacher).get(self._url())
        assert resp.status_code == 404

    def test_forbidden_returns_403(self):
        teacher = _make_teacher()
        with patch(
            "app.routers.students.list_student_recommendations",
            new_callable=AsyncMock,
            side_effect=ForbiddenError("You do not have access to this student."),
        ):
            resp = _client(teacher).get(self._url())
        assert resp.status_code == 403

    def test_unauthenticated_returns_401(self):
        resp = _anon_client().get(self._url())
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# POST /api/v1/classes/{classId}/groups/{groupId}/recommendations
# ---------------------------------------------------------------------------


class TestGenerateGroupRecommendationsEndpoint:
    _path = "/api/v1/classes/{class_id}/groups/{group_id}/recommendations"

    def _url(
        self,
        class_id: uuid.UUID | None = None,
        group_id: uuid.UUID | None = None,
    ) -> str:
        return self._path.format(
            class_id=class_id or uuid.uuid4(),
            group_id=group_id or uuid.uuid4(),
        )

    def _payload(self, **overrides) -> dict:
        base = {"grade_level": "Grade 8", "duration_minutes": 20}
        return {**base, **overrides}

    def test_happy_path_returns_201_with_envelope(self):
        teacher = _make_teacher()
        class_id = uuid.uuid4()
        group_id = uuid.uuid4()
        rec = _make_recommendation_orm(teacher_id=teacher.id, group_id=group_id, student_id=None)
        with patch(
            "app.routers.classes.generate_group_recommendations",
            new_callable=AsyncMock,
            return_value=rec,
        ):
            resp = _client(teacher).post(self._url(class_id, group_id), json=self._payload())
        assert resp.status_code == 201
        body = resp.json()
        assert "data" in body
        data = body["data"]
        assert data["grade_level"] == "Grade 8"
        assert data["status"] == "pending_review"
        assert len(data["recommendations"]) == 1

    def test_group_not_found_returns_404(self):
        teacher = _make_teacher()
        with patch(
            "app.routers.classes.generate_group_recommendations",
            new_callable=AsyncMock,
            side_effect=NotFoundError("Student group not found."),
        ):
            resp = _client(teacher).post(self._url(), json=self._payload())
        assert resp.status_code == 404

    def test_forbidden_returns_403(self):
        teacher = _make_teacher()
        with patch(
            "app.routers.classes.generate_group_recommendations",
            new_callable=AsyncMock,
            side_effect=ForbiddenError("You do not have access to this student group."),
        ):
            resp = _client(teacher).post(self._url(), json=self._payload())
        assert resp.status_code == 403

    def test_llm_service_unavailable_returns_503(self):
        teacher = _make_teacher()
        with patch(
            "app.routers.classes.generate_group_recommendations",
            new_callable=AsyncMock,
            side_effect=LLMError("LLM unavailable"),
        ):
            resp = _client(teacher).post(self._url(), json=self._payload())
        assert resp.status_code == 503

    def test_unauthenticated_returns_401(self):
        resp = _anon_client().post(self._url(), json=self._payload())
        assert resp.status_code == 401

    def test_missing_grade_level_returns_422(self):
        teacher = _make_teacher()
        resp = _client(teacher).post(self._url(), json={"duration_minutes": 20})
        assert resp.status_code == 422

    def test_invalid_duration_too_large_returns_422(self):
        teacher = _make_teacher()
        resp = _client(teacher).post(
            self._url(), json={"grade_level": "Grade 8", "duration_minutes": 999}
        )
        assert resp.status_code == 422

    def test_cross_teacher_access_returns_403(self):
        """A teacher cannot generate recommendations for another teacher's group."""
        teacher = _make_teacher()

        with patch(
            "app.routers.classes.generate_group_recommendations",
            new_callable=AsyncMock,
            side_effect=ForbiddenError("You do not have access to this student group."),
        ):
            resp = _client(teacher).post(self._url(), json=self._payload())
        assert resp.status_code == 403
