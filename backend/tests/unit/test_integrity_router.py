"""Unit tests for the integrity router endpoints (M4.6).

Tests cover:
- GET  /api/v1/essays/{id}/integrity              — happy path, 401, 403, 404
- PATCH /api/v1/integrity-reports/{id}/status     — happy path, 401, 403, 404, 422
- GET  /api/v1/assignments/{id}/integrity/summary — happy path, 401, 403, 404

No real PostgreSQL.  All DB / service calls are mocked.
No student PII in fixtures.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.dependencies import get_current_teacher
from app.exceptions import ForbiddenError, NotFoundError, ValidationError
from app.main import create_app
from app.models.integrity_report import IntegrityReportStatus
from app.schemas.integrity import IntegrityReportResponse, IntegritySummaryResponse

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_teacher(teacher_id: uuid.UUID | None = None) -> MagicMock:
    teacher = MagicMock()
    teacher.id = teacher_id or uuid.uuid4()
    teacher.email = "teacher@school.edu"
    teacher.email_verified = True
    return teacher


def _make_report(
    report_id: uuid.UUID | None = None,
    essay_version_id: uuid.UUID | None = None,
    status: IntegrityReportStatus = IntegrityReportStatus.pending,
) -> IntegrityReportResponse:
    return IntegrityReportResponse(
        id=report_id or uuid.uuid4(),
        essay_version_id=essay_version_id or uuid.uuid4(),
        provider="internal",
        ai_likelihood=0.25,
        similarity_score=0.1,
        flagged_passages=[],
        status=status,
        reviewed_at=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def _make_summary(
    assignment_id: uuid.UUID | None = None,
) -> IntegritySummaryResponse:
    return IntegritySummaryResponse(
        assignment_id=assignment_id or uuid.uuid4(),
        flagged=2,
        reviewed_clear=1,
        pending=3,
        total=6,
    )


def _app_with_teacher(teacher: MagicMock | None = None) -> object:
    teacher = teacher or _make_teacher()
    app = create_app()
    app.dependency_overrides[get_current_teacher] = lambda: teacher  # type: ignore[attr-defined]
    return app


def _unauthed_app() -> object:
    """App with no dependency override → get_current_teacher returns 401."""
    from app.exceptions import UnauthorizedError

    app = create_app()
    app.dependency_overrides[get_current_teacher] = lambda: (_ for _ in ()).throw(  # type: ignore[attr-defined]
        UnauthorizedError("Not authenticated.")
    )
    return app


# ---------------------------------------------------------------------------
# GET /api/v1/essays/{id}/integrity
# ---------------------------------------------------------------------------


class TestGetEssayIntegrity:
    def _url(self, essay_id: uuid.UUID | None = None) -> str:
        eid = essay_id or uuid.uuid4()
        return f"/api/v1/essays/{eid}/integrity"

    def test_happy_path_returns_report(self) -> None:
        teacher = _make_teacher()
        essay_id = uuid.uuid4()
        report = _make_report()
        app = _app_with_teacher(teacher)

        with patch(
            "app.routers.integrity.get_integrity_report_for_essay",
            new_callable=AsyncMock,
            return_value=report,
        ):
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.get(self._url(essay_id))

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "data" in body
        assert body["data"]["id"] == str(report.id)
        assert body["data"]["provider"] == "internal"
        assert body["data"]["status"] == "pending"

    def test_returns_401_when_unauthenticated(self) -> None:
        app = _unauthed_app()
        with patch("app.routers.integrity.get_integrity_report_for_essay"):
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.get(self._url())
        assert resp.status_code == 401

    def test_returns_403_when_essay_belongs_to_different_teacher(self) -> None:
        teacher = _make_teacher()
        app = _app_with_teacher(teacher)

        with patch(
            "app.routers.integrity.get_integrity_report_for_essay",
            new_callable=AsyncMock,
            side_effect=ForbiddenError("You do not have access to this essay."),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.get(self._url())

        assert resp.status_code == 403
        body = resp.json()
        assert body["error"]["code"] == "FORBIDDEN"

    def test_returns_404_when_essay_not_found(self) -> None:
        teacher = _make_teacher()
        app = _app_with_teacher(teacher)

        with patch(
            "app.routers.integrity.get_integrity_report_for_essay",
            new_callable=AsyncMock,
            side_effect=NotFoundError("Essay not found."),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.get(self._url())

        assert resp.status_code == 404
        body = resp.json()
        assert body["error"]["code"] == "NOT_FOUND"

    def test_returns_404_when_no_integrity_report_exists(self) -> None:
        teacher = _make_teacher()
        app = _app_with_teacher(teacher)

        with patch(
            "app.routers.integrity.get_integrity_report_for_essay",
            new_callable=AsyncMock,
            side_effect=NotFoundError("No integrity report found for this essay."),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.get(self._url())

        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# PATCH /api/v1/integrity-reports/{id}/status
# ---------------------------------------------------------------------------


class TestPatchIntegrityStatus:
    def _url(self, report_id: uuid.UUID | None = None) -> str:
        rid = report_id or uuid.uuid4()
        return f"/api/v1/integrity-reports/{rid}/status"

    def test_happy_path_reviewed_clear(self) -> None:
        teacher = _make_teacher()
        report = _make_report(status=IntegrityReportStatus.reviewed_clear)
        app = _app_with_teacher(teacher)

        with patch(
            "app.routers.integrity.update_integrity_report_status",
            new_callable=AsyncMock,
            return_value=report,
        ):
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.patch(
                self._url(report.id),
                json={"status": "reviewed_clear"},
            )

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["data"]["status"] == "reviewed_clear"

    def test_happy_path_flagged(self) -> None:
        teacher = _make_teacher()
        report = _make_report(status=IntegrityReportStatus.flagged)
        app = _app_with_teacher(teacher)

        with patch(
            "app.routers.integrity.update_integrity_report_status",
            new_callable=AsyncMock,
            return_value=report,
        ):
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.patch(
                self._url(report.id),
                json={"status": "flagged"},
            )

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["data"]["status"] == "flagged"

    def test_returns_422_when_status_is_pending(self) -> None:
        teacher = _make_teacher()
        app = _app_with_teacher(teacher)

        client = TestClient(app, raise_server_exceptions=False)
        resp = client.patch(
            self._url(),
            json={"status": "pending"},
        )

        assert resp.status_code == 422
        body = resp.json()
        assert body["error"]["code"] == "VALIDATION_ERROR"

    def test_returns_401_when_unauthenticated(self) -> None:
        app = _unauthed_app()
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.patch(self._url(), json={"status": "flagged"})
        assert resp.status_code == 401

    def test_returns_403_when_report_belongs_to_different_teacher(self) -> None:
        teacher = _make_teacher()
        app = _app_with_teacher(teacher)

        with patch(
            "app.routers.integrity.update_integrity_report_status",
            new_callable=AsyncMock,
            side_effect=ForbiddenError(
                "You do not have access to this integrity report."
            ),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.patch(self._url(), json={"status": "flagged"})

        assert resp.status_code == 403
        body = resp.json()
        assert body["error"]["code"] == "FORBIDDEN"

    def test_returns_404_when_report_not_found(self) -> None:
        teacher = _make_teacher()
        app = _app_with_teacher(teacher)

        with patch(
            "app.routers.integrity.update_integrity_report_status",
            new_callable=AsyncMock,
            side_effect=NotFoundError("Integrity report not found."),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.patch(self._url(), json={"status": "reviewed_clear"})

        assert resp.status_code == 404

    def test_returns_422_for_missing_status_field(self) -> None:
        teacher = _make_teacher()
        app = _app_with_teacher(teacher)

        client = TestClient(app, raise_server_exceptions=False)
        resp = client.patch(self._url(), json={})

        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET /api/v1/assignments/{id}/integrity/summary
# ---------------------------------------------------------------------------


class TestGetAssignmentIntegritySummary:
    def _url(self, assignment_id: uuid.UUID | None = None) -> str:
        aid = assignment_id or uuid.uuid4()
        return f"/api/v1/assignments/{aid}/integrity/summary"

    def test_happy_path_returns_counts(self) -> None:
        teacher = _make_teacher()
        assignment_id = uuid.uuid4()
        summary = _make_summary(assignment_id=assignment_id)
        app = _app_with_teacher(teacher)

        with patch(
            "app.routers.integrity.get_integrity_summary_for_assignment",
            new_callable=AsyncMock,
            return_value=summary,
        ):
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.get(self._url(assignment_id))

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "data" in body
        data = body["data"]
        assert data["flagged"] == 2
        assert data["reviewed_clear"] == 1
        assert data["pending"] == 3
        assert data["total"] == 6

    def test_returns_401_when_unauthenticated(self) -> None:
        app = _unauthed_app()
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get(self._url())
        assert resp.status_code == 401

    def test_returns_403_when_assignment_belongs_to_different_teacher(self) -> None:
        teacher = _make_teacher()
        app = _app_with_teacher(teacher)

        with patch(
            "app.routers.integrity.get_integrity_summary_for_assignment",
            new_callable=AsyncMock,
            side_effect=ForbiddenError("You do not have access to this assignment."),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.get(self._url())

        assert resp.status_code == 403
        body = resp.json()
        assert body["error"]["code"] == "FORBIDDEN"

    def test_returns_404_when_assignment_not_found(self) -> None:
        teacher = _make_teacher()
        app = _app_with_teacher(teacher)

        with patch(
            "app.routers.integrity.get_integrity_summary_for_assignment",
            new_callable=AsyncMock,
            side_effect=NotFoundError("Assignment not found."),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.get(self._url())

        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Tenant isolation: cross-teacher access
# ---------------------------------------------------------------------------


class TestIntegrityTenantIsolation:
    """Verify that cross-teacher access returns 403, not 404.

    The spec requires: 'Cross-teacher access returns 403'.
    """

    def test_get_essay_integrity_cross_teacher_returns_403(self) -> None:
        teacher = _make_teacher()
        app = _app_with_teacher(teacher)

        with patch(
            "app.routers.integrity.get_integrity_report_for_essay",
            new_callable=AsyncMock,
            side_effect=ForbiddenError("You do not have access to this essay."),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.get(f"/api/v1/essays/{uuid.uuid4()}/integrity")

        assert resp.status_code == 403
        # Must not be 404 (which would leak existence)
        assert resp.status_code != 404

    def test_patch_integrity_status_cross_teacher_returns_403(self) -> None:
        teacher = _make_teacher()
        app = _app_with_teacher(teacher)

        with patch(
            "app.routers.integrity.update_integrity_report_status",
            new_callable=AsyncMock,
            side_effect=ForbiddenError(
                "You do not have access to this integrity report."
            ),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.patch(
                f"/api/v1/integrity-reports/{uuid.uuid4()}/status",
                json={"status": "flagged"},
            )

        assert resp.status_code == 403
        assert resp.status_code != 404
