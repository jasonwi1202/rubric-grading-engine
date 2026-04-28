"""Unit tests for M5-09 browser-compose essay service and router endpoints.

Covers:
- create_composed_essay: happy path, cross-teacher 403, 404 assignment
- save_writing_snapshot: happy path, snapshot accumulation, cross-teacher 403
- get_writing_snapshots: happy path, recovery after refresh, cross-teacher 403
- POST /api/v1/assignments/{id}/essays/compose: 201, 401, 403, 404
- POST /api/v1/essays/{id}/snapshots: 200, 401, 403, 404
- GET  /api/v1/essays/{id}/snapshots: 200, 401, 403, 404

No real PostgreSQL, S3, or file I/O.  All external calls are mocked.
No student PII in fixtures.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.dependencies import get_current_teacher
from app.exceptions import ForbiddenError, NotFoundError, ValidationError
from app.main import create_app
from app.schemas.essay import (
    ComposeEssayResponse,
    GetSnapshotsResponse,
    SnapshotItem,
    WriteSnapshotResponse,
)
from app.services.essay import _sanitize_html_content, _strip_html_tags, create_composed_essay

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _make_teacher(teacher_id: uuid.UUID | None = None) -> MagicMock:
    t = MagicMock()
    t.id = teacher_id or uuid.uuid4()
    t.email = "teacher@school.edu"
    t.email_verified = True
    return t


def _make_essay(
    essay_id: uuid.UUID | None = None,
    assignment_id: uuid.UUID | None = None,
    student_id: uuid.UUID | None = None,
    status: str = "unassigned",
) -> MagicMock:
    e = MagicMock()
    e.id = essay_id or uuid.uuid4()
    e.assignment_id = assignment_id or uuid.uuid4()
    e.student_id = student_id
    e.status = status
    return e


# Sentinel class used by _make_version to distinguish "caller passed None" from "no value provided".
class _UnsetType:
    pass


_UNSET = _UnsetType()


def _make_version(
    version_id: uuid.UUID | None = None,
    essay_id: uuid.UUID | None = None,
    writing_snapshots: list[Any] | None | _UnsetType = _UNSET,
    word_count: int = 0,
) -> MagicMock:
    v = MagicMock()
    v.id = version_id or uuid.uuid4()
    v.essay_id = essay_id or uuid.uuid4()
    v.word_count = word_count
    # Allow None to be explicitly set (represents a file-upload essay with no snapshot array).
    v.writing_snapshots = [] if isinstance(writing_snapshots, _UnsetType) else writing_snapshots
    v.content = ""
    v.submitted_at = datetime.now(UTC)
    return v


def _app_with_teacher(teacher: MagicMock | None = None) -> Any:
    teacher = teacher or _make_teacher()
    app = create_app()
    app.dependency_overrides[get_current_teacher] = lambda: teacher  # type: ignore[attr-defined]
    return app


# ---------------------------------------------------------------------------
# _strip_html_tags — unit tests
# ---------------------------------------------------------------------------


class TestStripHtmlTags:
    def test_strips_simple_tags(self) -> None:
        assert _strip_html_tags("<p>Hello world</p>") == "Hello world"

    def test_converts_block_tags_to_newlines(self) -> None:
        result = _strip_html_tags("<p>Paragraph one</p><p>Paragraph two</p>")
        assert "Paragraph one" in result
        assert "Paragraph two" in result

    def test_decodes_html_entities(self) -> None:
        assert "&amp;" not in _strip_html_tags("&amp;")
        result = _strip_html_tags("Tom &amp; Jerry")
        assert "Tom & Jerry" in result

    def test_handles_bold_italic(self) -> None:
        result = _strip_html_tags("<b>Bold</b> and <i>italic</i>")
        assert "Bold" in result
        assert "italic" in result
        assert "<b>" not in result

    def test_empty_string(self) -> None:
        assert _strip_html_tags("") == ""

    def test_no_tags(self) -> None:
        assert _strip_html_tags("Plain text") == "Plain text"


# ---------------------------------------------------------------------------
# _sanitize_html_content — unit tests
# ---------------------------------------------------------------------------


class TestSanitizeHtmlContent:
    def test_passes_safe_formatting_through(self) -> None:
        html = "<p>Hello <b>world</b></p>"
        assert _sanitize_html_content(html) == html

    def test_strips_script_tags_and_preserves_text(self) -> None:
        result = _sanitize_html_content("<script>alert(1)</script><p>text</p>")
        # The <script> tag itself is removed (no executable code).
        assert "<script>" not in result
        assert "</script>" not in result
        # Legitimate paragraph content is preserved.
        assert "<p>text</p>" in result

    def test_strips_event_handler_attributes(self) -> None:
        result = _sanitize_html_content('<p onclick="alert(1)">text</p>')
        assert 'onclick' not in result
        assert "<p>" in result
        assert "text" in result

    def test_strips_disallowed_tags_but_keeps_text(self) -> None:
        result = _sanitize_html_content("<img src='x' onerror='alert(1)'>")
        assert "<img" not in result

    def test_empty_string(self) -> None:
        assert _sanitize_html_content("") == ""

    def test_entity_round_trip(self) -> None:
        """HTML entities in text are preserved correctly after sanitization."""
        result = _sanitize_html_content("<p>Tom &amp; Jerry</p>")
        assert result == "<p>Tom &amp; Jerry</p>"


# ---------------------------------------------------------------------------
# create_composed_essay — service unit tests (mocked DB)
# ---------------------------------------------------------------------------


class TestCreateComposedEssay:
    @pytest.mark.asyncio
    async def test_happy_path_no_student(self) -> None:
        """Creates an essay with empty content and empty writing_snapshots."""
        teacher_id = uuid.uuid4()
        assignment_id = uuid.uuid4()

        assignment = MagicMock()
        assignment.id = assignment_id
        assignment.class_id = uuid.uuid4()

        essay = _make_essay(assignment_id=assignment_id)
        version = _make_version(essay_id=essay.id, writing_snapshots=[])

        # Use MagicMock for the db so sync methods (add) are not AsyncMocks.
        db = MagicMock()
        db.flush = AsyncMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        with (
            patch(
                "app.services.essay._get_assignment_for_teacher",
                new=AsyncMock(return_value=assignment),
            ),
            patch(
                "app.services.essay.Essay",
                return_value=essay,
            ),
            patch(
                "app.services.essay.EssayVersion",
                return_value=version,
            ),
        ):
            result = await create_composed_essay(
                db=db,
                teacher_id=teacher_id,
                assignment_id=assignment_id,
                student_id=None,
            )

        assert result.essay_id == essay.id
        assert result.essay_version_id == version.id
        assert result.assignment_id == assignment_id
        assert result.student_id is None
        assert result.current_content == ""
        assert result.word_count == 0

    @pytest.mark.asyncio
    async def test_cross_teacher_raises_forbidden(self) -> None:
        """_get_assignment_for_teacher raises ForbiddenError → propagates."""
        db = AsyncMock()

        with patch(
            "app.services.essay._get_assignment_for_teacher",
            new=AsyncMock(side_effect=ForbiddenError("forbidden")),
        ), pytest.raises(ForbiddenError):
            await create_composed_essay(
                db=db,
                teacher_id=uuid.uuid4(),
                assignment_id=uuid.uuid4(),
            )

    @pytest.mark.asyncio
    async def test_assignment_not_found_raises_not_found(self) -> None:
        """_get_assignment_for_teacher raises NotFoundError → propagates."""
        db = AsyncMock()

        with patch(
            "app.services.essay._get_assignment_for_teacher",
            new=AsyncMock(side_effect=NotFoundError("not found")),
        ), pytest.raises(NotFoundError):
            await create_composed_essay(
                db=db,
                teacher_id=uuid.uuid4(),
                assignment_id=uuid.uuid4(),
            )


# ---------------------------------------------------------------------------
# save_writing_snapshot — service unit tests (mocked DB)
# ---------------------------------------------------------------------------


class TestSaveWritingSnapshot:
    @pytest.mark.asyncio
    async def test_appends_snapshot_and_updates_content(self) -> None:
        """First snapshot: seq=1, content updated, writing_snapshots has one entry."""
        from app.services.essay import save_writing_snapshot

        teacher_id = uuid.uuid4()
        essay_id = uuid.uuid4()
        html = "<p>Hello world</p>"
        word_count = 2

        version = _make_version(essay_id=essay_id, writing_snapshots=[])
        version.id = uuid.uuid4()

        scalar_mock = MagicMock()
        scalar_mock.scalar_one_or_none.return_value = version

        # Use MagicMock for the db so sync methods (add) are not AsyncMocks.
        db = MagicMock()
        db.execute = AsyncMock(return_value=scalar_mock)
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        result = await save_writing_snapshot(
            db=db,
            teacher_id=teacher_id,
            essay_id=essay_id,
            html_content=html,
            word_count=word_count,
        )

        assert result.essay_id == essay_id
        assert result.snapshot_count == 1
        assert result.word_count == word_count
        # The version should have been mutated in place
        assert len(version.writing_snapshots) == 1
        snap = version.writing_snapshots[0]
        assert snap["seq"] == 1
        assert snap["word_count"] == word_count
        # html_content stored is the sanitized form; for safe input it is identical
        assert snap["html_content"] == html
        assert "ts" in snap

    @pytest.mark.asyncio
    async def test_accumulates_multiple_snapshots(self) -> None:
        """Second snapshot: seq=2, writing_snapshots has two entries."""
        from app.services.essay import save_writing_snapshot

        teacher_id = uuid.uuid4()
        essay_id = uuid.uuid4()
        html2 = "<p>Hello world extended</p>"
        word_count2 = 3

        # Simulate version after first snapshot
        first_snap = {
            "seq": 1,
            "ts": "2026-04-28T10:00:00+00:00",
            "word_count": 2,
            "html_content": "<p>Hello world</p>",
        }
        version = _make_version(essay_id=essay_id, writing_snapshots=[first_snap])
        version.id = uuid.uuid4()

        scalar_mock = MagicMock()
        scalar_mock.scalar_one_or_none.return_value = version

        db = MagicMock()
        db.execute = AsyncMock(return_value=scalar_mock)
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        result = await save_writing_snapshot(
            db=db,
            teacher_id=teacher_id,
            essay_id=essay_id,
            html_content=html2,
            word_count=word_count2,
        )

        assert result.snapshot_count == 2
        assert len(version.writing_snapshots) == 2
        assert version.writing_snapshots[1]["seq"] == 2

    @pytest.mark.asyncio
    async def test_file_upload_essay_raises_validation_error(self) -> None:
        """writing_snapshots=None (file-upload essay) raises ValidationError."""
        from app.services.essay import save_writing_snapshot

        # writing_snapshots=None represents a file-upload essay (no snapshot array).
        version = _make_version(writing_snapshots=None)

        scalar_mock = MagicMock()
        scalar_mock.scalar_one_or_none.return_value = version

        db = MagicMock()
        db.execute = AsyncMock(return_value=scalar_mock)
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        with pytest.raises(ValidationError):
            await save_writing_snapshot(
                db=db,
                teacher_id=uuid.uuid4(),
                essay_id=uuid.uuid4(),
                html_content="<p>text</p>",
                word_count=1,
            )

    @pytest.mark.asyncio
    async def test_cross_teacher_raises_forbidden(self) -> None:
        """JOIN returns None → _get_essay_for_teacher raises ForbiddenError."""
        from app.services.essay import save_writing_snapshot

        # The JOIN query returns None (cross-teacher access — teacher_id mismatch).
        scalar_mock = MagicMock()
        scalar_mock.scalar_one_or_none.return_value = None

        db = MagicMock()
        db.execute = AsyncMock(return_value=scalar_mock)

        with patch(
            "app.services.essay._get_essay_for_teacher",
            new=AsyncMock(side_effect=ForbiddenError("forbidden")),
        ), pytest.raises(ForbiddenError):
            await save_writing_snapshot(
                db=db,
                teacher_id=uuid.uuid4(),
                essay_id=uuid.uuid4(),
                html_content="<p>text</p>",
                word_count=1,
            )

    @pytest.mark.asyncio
    async def test_version_not_found_raises_not_found(self) -> None:
        """JOIN returns None and essay exists for teacher → NotFoundError for missing version."""
        from app.services.essay import save_writing_snapshot

        essay = _make_essay()

        # The JOIN query returns None (essay exists but has no version row).
        scalar_mock = MagicMock()
        scalar_mock.scalar_one_or_none.return_value = None

        db = MagicMock()
        db.execute = AsyncMock(return_value=scalar_mock)

        with patch(
            "app.services.essay._get_essay_for_teacher",
            new=AsyncMock(return_value=essay),
        ), pytest.raises(NotFoundError):
            await save_writing_snapshot(
                db=db,
                teacher_id=uuid.uuid4(),
                essay_id=uuid.uuid4(),
                html_content="<p>text</p>",
                word_count=1,
            )


# ---------------------------------------------------------------------------
# get_writing_snapshots — service unit tests (mocked DB)
# ---------------------------------------------------------------------------


class TestGetWritingSnapshots:
    @pytest.mark.asyncio
    async def test_returns_current_content_and_metadata(self) -> None:
        from app.services.essay import get_writing_snapshots

        teacher_id = uuid.uuid4()
        essay_id = uuid.uuid4()
        html = "<p>Final content</p>"
        snaps = [
            {"seq": 1, "ts": "2026-04-28T10:00:00+00:00", "word_count": 2, "html_content": "<p>First</p>"},
            {"seq": 2, "ts": "2026-04-28T10:00:12+00:00", "word_count": 3, "html_content": html},
        ]
        version = _make_version(essay_id=essay_id, writing_snapshots=snaps, word_count=3)
        version.id = uuid.uuid4()

        scalar_mock = MagicMock()
        scalar_mock.scalar_one_or_none.return_value = version

        db = MagicMock()
        db.execute = AsyncMock(return_value=scalar_mock)

        result = await get_writing_snapshots(db=db, teacher_id=teacher_id, essay_id=essay_id)

        assert result.essay_id == essay_id
        assert result.essay_version_id == version.id
        assert result.current_content == html  # latest snapshot's html_content
        assert result.word_count == 3
        assert len(result.snapshots) == 2
        assert result.snapshots[0].seq == 1
        assert result.snapshots[1].seq == 2

    @pytest.mark.asyncio
    async def test_empty_snapshots_returns_empty_content(self) -> None:
        from app.services.essay import get_writing_snapshots

        version = _make_version(writing_snapshots=[], word_count=0)
        version.id = uuid.uuid4()

        scalar_mock = MagicMock()
        scalar_mock.scalar_one_or_none.return_value = version

        db = MagicMock()
        db.execute = AsyncMock(return_value=scalar_mock)

        result = await get_writing_snapshots(
            db=db, teacher_id=uuid.uuid4(), essay_id=uuid.uuid4()
        )

        assert result.current_content == ""
        assert result.snapshots == []

    @pytest.mark.asyncio
    async def test_cross_teacher_raises_forbidden(self) -> None:
        """JOIN returns None → _get_essay_for_teacher raises ForbiddenError."""
        from app.services.essay import get_writing_snapshots

        # The JOIN query returns None (cross-teacher mismatch).
        scalar_mock = MagicMock()
        scalar_mock.scalar_one_or_none.return_value = None

        db = MagicMock()
        db.execute = AsyncMock(return_value=scalar_mock)

        with patch(
            "app.services.essay._get_essay_for_teacher",
            new=AsyncMock(side_effect=ForbiddenError("forbidden")),
        ), pytest.raises(ForbiddenError):
            await get_writing_snapshots(
                db=db, teacher_id=uuid.uuid4(), essay_id=uuid.uuid4()
            )


# ---------------------------------------------------------------------------
# Router — POST /assignments/{id}/essays/compose
# ---------------------------------------------------------------------------


class TestComposeEssayEndpoint:
    def test_201_happy_path(self) -> None:
        teacher = _make_teacher()
        app = _app_with_teacher(teacher)
        assignment_id = uuid.uuid4()
        essay_id = uuid.uuid4()
        version_id = uuid.uuid4()

        expected = ComposeEssayResponse(
            essay_id=essay_id,
            essay_version_id=version_id,
            assignment_id=assignment_id,
            student_id=None,
            status="unassigned",
            current_content="",
            word_count=0,
        )

        with patch(
            "app.routers.essays.create_composed_essay",
            new=AsyncMock(return_value=expected),
        ):
            client = TestClient(app)
            resp = client.post(
                f"/api/v1/assignments/{assignment_id}/essays/compose",
                json={},
            )

        assert resp.status_code == 201
        data = resp.json()["data"]
        assert data["essay_id"] == str(essay_id)
        assert data["essay_version_id"] == str(version_id)
        assert data["current_content"] == ""
        assert data["word_count"] == 0

    def test_401_no_auth(self) -> None:
        app = create_app()
        client = TestClient(app)
        resp = client.post(f"/api/v1/assignments/{uuid.uuid4()}/essays/compose", json={})
        assert resp.status_code == 401

    def test_403_cross_teacher(self) -> None:
        teacher = _make_teacher()
        app = _app_with_teacher(teacher)

        with patch(
            "app.routers.essays.create_composed_essay",
            new=AsyncMock(side_effect=ForbiddenError("forbidden")),
        ):
            client = TestClient(app)
            resp = client.post(
                f"/api/v1/assignments/{uuid.uuid4()}/essays/compose",
                json={},
            )

        assert resp.status_code == 403

    def test_404_no_assignment(self) -> None:
        teacher = _make_teacher()
        app = _app_with_teacher(teacher)

        with patch(
            "app.routers.essays.create_composed_essay",
            new=AsyncMock(side_effect=NotFoundError("not found")),
        ):
            client = TestClient(app)
            resp = client.post(
                f"/api/v1/assignments/{uuid.uuid4()}/essays/compose",
                json={},
            )

        assert resp.status_code == 404

    def test_201_with_student_id(self) -> None:
        teacher = _make_teacher()
        app = _app_with_teacher(teacher)
        assignment_id = uuid.uuid4()
        student_id = uuid.uuid4()
        essay_id = uuid.uuid4()
        version_id = uuid.uuid4()

        expected = ComposeEssayResponse(
            essay_id=essay_id,
            essay_version_id=version_id,
            assignment_id=assignment_id,
            student_id=student_id,
            status="queued",
            current_content="",
            word_count=0,
        )

        with patch(
            "app.routers.essays.create_composed_essay",
            new=AsyncMock(return_value=expected),
        ) as mock_svc:
            client = TestClient(app)
            resp = client.post(
                f"/api/v1/assignments/{assignment_id}/essays/compose",
                json={"student_id": str(student_id)},
            )

        assert resp.status_code == 201
        assert resp.json()["data"]["student_id"] == str(student_id)
        mock_svc.assert_called_once()
        call_kwargs = mock_svc.call_args.kwargs
        assert call_kwargs["student_id"] == student_id


# ---------------------------------------------------------------------------
# Router — POST /essays/{id}/snapshots
# ---------------------------------------------------------------------------


class TestSaveSnapshotEndpoint:
    def test_200_happy_path(self) -> None:
        teacher = _make_teacher()
        app = _app_with_teacher(teacher)
        essay_id = uuid.uuid4()
        version_id = uuid.uuid4()

        expected = WriteSnapshotResponse(
            essay_id=essay_id,
            essay_version_id=version_id,
            snapshot_count=1,
            word_count=5,
            saved_at=datetime.now(UTC),
        )

        with patch(
            "app.routers.essays.save_writing_snapshot",
            new=AsyncMock(return_value=expected),
        ):
            client = TestClient(app)
            resp = client.post(
                f"/api/v1/essays/{essay_id}/snapshots",
                json={"html_content": "<p>Hello world</p>", "word_count": 5},
            )

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["snapshot_count"] == 1
        assert data["word_count"] == 5

    def test_401_no_auth(self) -> None:
        app = create_app()
        client = TestClient(app)
        resp = client.post(
            f"/api/v1/essays/{uuid.uuid4()}/snapshots",
            json={"html_content": "<p>text</p>", "word_count": 1},
        )
        assert resp.status_code == 401

    def test_403_cross_teacher(self) -> None:
        teacher = _make_teacher()
        app = _app_with_teacher(teacher)

        with patch(
            "app.routers.essays.save_writing_snapshot",
            new=AsyncMock(side_effect=ForbiddenError("forbidden")),
        ):
            client = TestClient(app)
            resp = client.post(
                f"/api/v1/essays/{uuid.uuid4()}/snapshots",
                json={"html_content": "<p>text</p>", "word_count": 1},
            )

        assert resp.status_code == 403

    def test_404_no_essay(self) -> None:
        teacher = _make_teacher()
        app = _app_with_teacher(teacher)

        with patch(
            "app.routers.essays.save_writing_snapshot",
            new=AsyncMock(side_effect=NotFoundError("not found")),
        ):
            client = TestClient(app)
            resp = client.post(
                f"/api/v1/essays/{uuid.uuid4()}/snapshots",
                json={"html_content": "<p>text</p>", "word_count": 1},
            )

        assert resp.status_code == 404

    def test_422_missing_html_content(self) -> None:
        teacher = _make_teacher()
        app = _app_with_teacher(teacher)

        client = TestClient(app)
        resp = client.post(
            f"/api/v1/essays/{uuid.uuid4()}/snapshots",
            json={"word_count": 5},
        )
        assert resp.status_code == 422

    def test_422_content_too_long(self) -> None:
        teacher = _make_teacher()
        app = _app_with_teacher(teacher)

        client = TestClient(app)
        resp = client.post(
            f"/api/v1/essays/{uuid.uuid4()}/snapshots",
            json={"html_content": "a" * 500_001, "word_count": 1},
        )
        assert resp.status_code == 422

    def test_calls_service_with_correct_args(self) -> None:
        teacher = _make_teacher()
        app = _app_with_teacher(teacher)
        essay_id = uuid.uuid4()
        html = "<p>Essay content here</p>"
        wc = 3

        expected = WriteSnapshotResponse(
            essay_id=essay_id,
            essay_version_id=uuid.uuid4(),
            snapshot_count=1,
            word_count=wc,
            saved_at=datetime.now(UTC),
        )

        with patch(
            "app.routers.essays.save_writing_snapshot",
            new=AsyncMock(return_value=expected),
        ) as mock_svc:
            client = TestClient(app)
            client.post(
                f"/api/v1/essays/{essay_id}/snapshots",
                json={"html_content": html, "word_count": wc},
            )

        mock_svc.assert_called_once()
        kwargs = mock_svc.call_args.kwargs
        assert kwargs["essay_id"] == essay_id
        assert kwargs["html_content"] == html
        assert kwargs["word_count"] == wc
        assert kwargs["teacher_id"] == teacher.id


# ---------------------------------------------------------------------------
# Router — GET /essays/{id}/snapshots
# ---------------------------------------------------------------------------


class TestGetSnapshotsEndpoint:
    def test_200_happy_path(self) -> None:
        teacher = _make_teacher()
        app = _app_with_teacher(teacher)
        essay_id = uuid.uuid4()
        version_id = uuid.uuid4()

        expected = GetSnapshotsResponse(
            essay_id=essay_id,
            essay_version_id=version_id,
            current_content="<p>Latest content</p>",
            word_count=2,
            snapshots=[
                SnapshotItem(seq=1, ts="2026-04-28T10:00:00+00:00", word_count=2),
            ],
        )

        with patch(
            "app.routers.essays.get_writing_snapshots",
            new=AsyncMock(return_value=expected),
        ):
            client = TestClient(app)
            resp = client.get(f"/api/v1/essays/{essay_id}/snapshots")

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["current_content"] == "<p>Latest content</p>"
        assert data["word_count"] == 2
        assert len(data["snapshots"]) == 1
        assert data["snapshots"][0]["seq"] == 1

    def test_401_no_auth(self) -> None:
        app = create_app()
        client = TestClient(app)
        resp = client.get(f"/api/v1/essays/{uuid.uuid4()}/snapshots")
        assert resp.status_code == 401

    def test_403_cross_teacher(self) -> None:
        teacher = _make_teacher()
        app = _app_with_teacher(teacher)

        with patch(
            "app.routers.essays.get_writing_snapshots",
            new=AsyncMock(side_effect=ForbiddenError("forbidden")),
        ):
            client = TestClient(app)
            resp = client.get(f"/api/v1/essays/{uuid.uuid4()}/snapshots")

        assert resp.status_code == 403

    def test_404_no_essay(self) -> None:
        teacher = _make_teacher()
        app = _app_with_teacher(teacher)

        with patch(
            "app.routers.essays.get_writing_snapshots",
            new=AsyncMock(side_effect=NotFoundError("not found")),
        ):
            client = TestClient(app)
            resp = client.get(f"/api/v1/essays/{uuid.uuid4()}/snapshots")

        assert resp.status_code == 404

    def test_200_empty_snapshots(self) -> None:
        teacher = _make_teacher()
        app = _app_with_teacher(teacher)
        essay_id = uuid.uuid4()

        expected = GetSnapshotsResponse(
            essay_id=essay_id,
            essay_version_id=uuid.uuid4(),
            current_content="",
            word_count=0,
            snapshots=[],
        )

        with patch(
            "app.routers.essays.get_writing_snapshots",
            new=AsyncMock(return_value=expected),
        ):
            client = TestClient(app)
            resp = client.get(f"/api/v1/essays/{essay_id}/snapshots")

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["current_content"] == ""
        assert data["snapshots"] == []
