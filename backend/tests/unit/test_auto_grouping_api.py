"""Unit tests for GET /api/v1/classes/{classId}/groups.

Tests cover:
- Happy path: returns groups with correct shape and envelope.
- Empty groups: returns empty list when no groups have been computed.
- Cross-teacher denial: returns 404 (class not found under RLS).
- Not found: returns 404 when class does not exist.
- Authentication required: returns 401 when no credentials.
- Router passes teacher_id to service correctly.
- Stability values are included in the response (new / persistent / exited).

No real database.  All service calls are mocked.  No student PII.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Literal
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from app.dependencies import get_current_teacher
from app.exceptions import NotFoundError
from app.main import create_app
from app.schemas.student_group import (
    ClassGroupsResponse,
    StudentGroupResponse,
    StudentInGroupResponse,
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


def _make_student_in_group(
    student_id: uuid.UUID | None = None,
) -> StudentInGroupResponse:
    return StudentInGroupResponse(
        id=student_id or uuid.uuid4(),
        full_name="Student Placeholder",
        external_id=None,
    )


def _make_group_response(
    class_id: uuid.UUID,
    skill_key: str = "evidence",
    stability: Literal["new", "persistent", "exited"] = "persistent",
    student_count: int = 3,
) -> StudentGroupResponse:
    return StudentGroupResponse(
        id=uuid.uuid4(),
        skill_key=skill_key,
        label=skill_key.replace("_", " ").title(),
        student_count=student_count,
        students=[_make_student_in_group() for _ in range(student_count)],
        stability=stability,
        computed_at=datetime.now(UTC),
    )


def _make_class_groups_response(
    class_id: uuid.UUID,
) -> ClassGroupsResponse:
    return ClassGroupsResponse(
        class_id=class_id,
        groups=[
            _make_group_response(class_id, skill_key="evidence", stability="persistent"),
            _make_group_response(class_id, skill_key="thesis", stability="new"),
            _make_group_response(
                class_id, skill_key="organization", stability="exited", student_count=0
            ),
        ],
    )


# ---------------------------------------------------------------------------
# Tests — GET /api/v1/classes/{classId}/groups
# ---------------------------------------------------------------------------


class TestGetClassGroups:
    def test_returns_groups_with_data_envelope(self) -> None:
        teacher = _make_teacher()
        class_id = uuid.uuid4()
        groups_response = _make_class_groups_response(class_id)
        app = _app_with_teacher(teacher)
        with (
            patch(
                "app.routers.classes.list_class_groups",
                new_callable=AsyncMock,
                return_value=groups_response,
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.get(f"/api/v1/classes/{class_id}/groups")

        assert resp.status_code == 200, resp.text
        payload = resp.json()
        assert "data" in payload, "Response must use the {'data': ...} envelope"
        data = payload["data"]
        assert data["class_id"] == str(class_id)
        assert isinstance(data["groups"], list)
        assert len(data["groups"]) == 3

    def test_response_includes_skill_gap_labels(self) -> None:
        teacher = _make_teacher()
        class_id = uuid.uuid4()
        groups_response = _make_class_groups_response(class_id)
        app = _app_with_teacher(teacher)
        with (
            patch(
                "app.routers.classes.list_class_groups",
                new_callable=AsyncMock,
                return_value=groups_response,
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.get(f"/api/v1/classes/{class_id}/groups")

        groups = resp.json()["data"]["groups"]
        skill_keys = {g["skill_key"] for g in groups}
        assert "evidence" in skill_keys
        assert "thesis" in skill_keys
        assert "organization" in skill_keys
        for group in groups:
            assert "label" in group
            assert isinstance(group["label"], str)

    def test_response_includes_stability_status(self) -> None:
        teacher = _make_teacher()
        class_id = uuid.uuid4()
        groups_response = _make_class_groups_response(class_id)
        app = _app_with_teacher(teacher)
        with (
            patch(
                "app.routers.classes.list_class_groups",
                new_callable=AsyncMock,
                return_value=groups_response,
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.get(f"/api/v1/classes/{class_id}/groups")

        groups = resp.json()["data"]["groups"]
        stability_values = {g["stability"] for g in groups}
        assert "persistent" in stability_values
        assert "new" in stability_values
        assert "exited" in stability_values

    def test_response_includes_student_lists(self) -> None:
        teacher = _make_teacher()
        class_id = uuid.uuid4()
        groups_response = _make_class_groups_response(class_id)
        app = _app_with_teacher(teacher)
        with (
            patch(
                "app.routers.classes.list_class_groups",
                new_callable=AsyncMock,
                return_value=groups_response,
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.get(f"/api/v1/classes/{class_id}/groups")

        groups = resp.json()["data"]["groups"]
        for group in groups:
            assert "students" in group, "Each group must include a students list"
            assert isinstance(group["students"], list)
            assert "student_count" in group

    def test_exited_group_has_empty_student_list(self) -> None:
        teacher = _make_teacher()
        class_id = uuid.uuid4()
        groups_response = _make_class_groups_response(class_id)
        app = _app_with_teacher(teacher)
        with (
            patch(
                "app.routers.classes.list_class_groups",
                new_callable=AsyncMock,
                return_value=groups_response,
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.get(f"/api/v1/classes/{class_id}/groups")

        groups = resp.json()["data"]["groups"]
        exited = [g for g in groups if g["stability"] == "exited"]
        assert len(exited) == 1
        assert exited[0]["students"] == []
        assert exited[0]["student_count"] == 0

    def test_returns_empty_groups_list_when_none_computed(self) -> None:
        teacher = _make_teacher()
        class_id = uuid.uuid4()
        empty_response = ClassGroupsResponse(class_id=class_id, groups=[])
        app = _app_with_teacher(teacher)
        with (
            patch(
                "app.routers.classes.list_class_groups",
                new_callable=AsyncMock,
                return_value=empty_response,
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.get(f"/api/v1/classes/{class_id}/groups")

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["groups"] == []

    def test_returns_404_when_class_not_found(self) -> None:
        teacher = _make_teacher()
        class_id = uuid.uuid4()
        app = _app_with_teacher(teacher)
        with (
            patch(
                "app.routers.classes.list_class_groups",
                new_callable=AsyncMock,
                side_effect=NotFoundError("Class not found."),
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.get(f"/api/v1/classes/{class_id}/groups")

        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "NOT_FOUND"

    def test_returns_404_for_inaccessible_class(self) -> None:
        """Cross-teacher (or non-existent) class returns 404 under RLS.

        With Row-Level Security enabled in production, a class that belongs to
        a different teacher is indistinguishable from one that does not exist:
        both raise NotFoundError and surface as 404.
        """
        teacher = _make_teacher()
        class_id = uuid.uuid4()
        app = _app_with_teacher(teacher)
        with (
            patch(
                "app.routers.classes.list_class_groups",
                new_callable=AsyncMock,
                side_effect=NotFoundError("Class not found."),
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.get(f"/api/v1/classes/{class_id}/groups")

        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "NOT_FOUND"

    def test_requires_authentication(self) -> None:
        """Unauthenticated request must return 401."""
        app = create_app()
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get(f"/api/v1/classes/{uuid.uuid4()}/groups")
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "UNAUTHORIZED"

    def test_passes_teacher_id_and_class_id_to_service(self) -> None:
        """Router must forward the authenticated teacher's id to the service."""
        teacher = _make_teacher()
        class_id = uuid.uuid4()
        empty_response = ClassGroupsResponse(class_id=class_id, groups=[])
        app = _app_with_teacher(teacher)
        mock_service = AsyncMock(return_value=empty_response)
        with (
            patch("app.routers.classes.list_class_groups", mock_service),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            client.get(f"/api/v1/classes/{class_id}/groups")

        mock_service.assert_awaited_once()
        call_kwargs = mock_service.call_args
        # Verify teacher_id and class_id were passed to the service.
        assert teacher.id in call_kwargs.args
        assert class_id in call_kwargs.args


# ---------------------------------------------------------------------------
# Tests — stability tracking in _build_groups (M6-02 additions)
# ---------------------------------------------------------------------------


def _make_profile_mock(
    student_id: uuid.UUID,
    teacher_id: uuid.UUID,
    skills: dict[str, float],
) -> MagicMock:
    """Build a mock StudentSkillProfile with the given avg_scores per skill."""
    from typing import Any

    skill_scores: dict[str, Any] = {
        skill: {
            "avg_score": score,
            "trend": "stable",
            "data_points": 2,
            "last_updated": "2026-01-01T00:00:00+00:00",
        }
        for skill, score in skills.items()
    }
    profile = MagicMock()
    profile.student_id = student_id
    profile.teacher_id = teacher_id
    profile.skill_scores = skill_scores
    return profile


class TestBuildGroupsStabilityTracking:
    """Validate that _build_groups correctly assigns stability when
    previous_active_skill_keys is provided."""

    def test_new_group_when_skill_key_not_in_previous(self) -> None:
        from app.services.auto_grouping import _build_groups

        teacher_id = uuid.uuid4()
        profiles = [
            _make_profile_mock(uuid.uuid4(), teacher_id, {"evidence": 0.4}),
            _make_profile_mock(uuid.uuid4(), teacher_id, {"evidence": 0.5}),
        ]
        groups = _build_groups(
            profiles,
            underperformance_threshold=0.7,
            min_group_size=2,
            previous_active_skill_keys=set(),  # no previous groups
        )
        assert len(groups) == 1
        assert groups[0]["skill_key"] == "evidence"
        assert groups[0]["stability"] == "new"

    def test_persistent_group_when_skill_key_in_previous(self) -> None:
        from app.services.auto_grouping import _build_groups

        teacher_id = uuid.uuid4()
        profiles = [
            _make_profile_mock(uuid.uuid4(), teacher_id, {"thesis": 0.3}),
            _make_profile_mock(uuid.uuid4(), teacher_id, {"thesis": 0.4}),
        ]
        groups = _build_groups(
            profiles,
            underperformance_threshold=0.7,
            min_group_size=2,
            previous_active_skill_keys={"thesis"},  # thesis was active before
        )
        assert len(groups) == 1
        assert groups[0]["skill_key"] == "thesis"
        assert groups[0]["stability"] == "persistent"

    def test_mixed_stability_values_across_groups(self) -> None:
        from app.services.auto_grouping import _build_groups

        teacher_id = uuid.uuid4()
        sid1, sid2 = uuid.uuid4(), uuid.uuid4()
        profiles = [
            _make_profile_mock(sid1, teacher_id, {"evidence": 0.4, "thesis": 0.3}),
            _make_profile_mock(sid2, teacher_id, {"evidence": 0.5, "thesis": 0.5}),
        ]
        groups = _build_groups(
            profiles,
            underperformance_threshold=0.7,
            min_group_size=2,
            previous_active_skill_keys={"thesis"},  # only thesis was active
        )
        assert len(groups) == 2
        evidence_g = next(g for g in groups if g["skill_key"] == "evidence")
        thesis_g = next(g for g in groups if g["skill_key"] == "thesis")
        assert evidence_g["stability"] == "new"
        assert thesis_g["stability"] == "persistent"

    def test_no_previous_skill_keys_defaults_all_to_new(self) -> None:
        from app.services.auto_grouping import _build_groups

        teacher_id = uuid.uuid4()
        profiles = [
            _make_profile_mock(uuid.uuid4(), teacher_id, {"organization": 0.4}),
            _make_profile_mock(uuid.uuid4(), teacher_id, {"organization": 0.5}),
        ]
        # previous_active_skill_keys defaults to None → all 'new'
        groups = _build_groups(
            profiles,
            underperformance_threshold=0.7,
            min_group_size=2,
        )
        assert len(groups) == 1
        assert groups[0]["stability"] == "new"
