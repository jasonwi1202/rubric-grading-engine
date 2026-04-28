"""Unit tests for M5-10 composition timeline signal extraction.

Covers:
- analyze_writing_process: session segmentation, paste detection,
  rapid-completion detection, edge cases (empty, single snapshot,
  sparse/noisy sequences)
- get_process_signals service: happy path, cache hit, cache invalidation,
  cross-teacher 403, 404
- GET /api/v1/essays/{id}/process-signals: 200, 401, 403, 404

No real PostgreSQL, S3, or file I/O.  All external calls are mocked.
No student PII in fixtures.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.db.session import get_db
from app.dependencies import get_current_teacher
from app.exceptions import ForbiddenError, NotFoundError
from app.main import create_app
from app.services.composition_timeline import (
    analyze_writing_process,
)

# ---------------------------------------------------------------------------
# Snapshot factory helpers
# ---------------------------------------------------------------------------


def _snap(
    seq: int,
    ts: datetime,
    word_count: int,
    html_content: str = "",
) -> dict[str, Any]:
    return {
        "seq": seq,
        "ts": ts.isoformat(),
        "word_count": word_count,
        "html_content": html_content,
    }


def _ts(offset_minutes: float = 0.0) -> datetime:
    """Return an absolute UTC datetime anchored at a fixed point + offset."""
    base = datetime(2026, 4, 1, 10, 0, 0, tzinfo=UTC)
    return base + timedelta(minutes=offset_minutes)


# ---------------------------------------------------------------------------
# TestAnalyzeWritingProcess — core signal extraction logic
# ---------------------------------------------------------------------------


class TestAnalyzeWritingProcessEmpty:
    def test_empty_list_returns_no_process_data(self) -> None:
        result = analyze_writing_process([])
        assert result.has_process_data is False
        assert result.session_count == 0
        assert result.sessions == []
        assert result.paste_events == []
        assert result.rapid_completion_events == []
        assert result.active_writing_seconds == 0.0
        assert result.total_elapsed_seconds == 0.0
        assert result.inter_session_gaps_seconds == []

    def test_all_invalid_snapshots_returns_no_process_data(self) -> None:
        bad_snaps = [
            {"seq": "x", "ts": "not-a-date", "word_count": 0},
            {"ts": _ts().isoformat()},  # missing seq and word_count
            {},
        ]
        result = analyze_writing_process(bad_snaps)
        assert result.has_process_data is False
        assert result.session_count == 0


class TestAnalyzeWritingProcessSingleSnapshot:
    def test_single_snapshot_yields_one_session(self) -> None:
        snaps = [_snap(1, _ts(0), 100)]
        result = analyze_writing_process(snaps)
        assert result.has_process_data is True
        assert result.session_count == 1
        assert len(result.sessions) == 1
        session = result.sessions[0]
        assert session.session_index == 0
        assert session.snapshot_count == 1
        assert session.duration_seconds == 0.0
        assert session.word_count_start == 100
        assert session.word_count_end == 100
        assert session.words_added == 0

    def test_single_snapshot_no_inter_gaps(self) -> None:
        snaps = [_snap(1, _ts(0), 50)]
        result = analyze_writing_process(snaps)
        assert result.inter_session_gaps_seconds == []

    def test_single_snapshot_no_events(self) -> None:
        snaps = [_snap(1, _ts(0), 200)]
        result = analyze_writing_process(snaps)
        assert result.paste_events == []
        assert result.rapid_completion_events == []


class TestSessionSegmentation:
    def test_snapshots_within_gap_form_single_session(self) -> None:
        """Ten snapshots spaced 30 seconds apart → one session."""
        snaps = [_snap(i + 1, _ts(i * 0.5), i * 10) for i in range(10)]
        result = analyze_writing_process(snaps, session_gap_seconds=1800.0)
        assert result.session_count == 1
        assert result.inter_session_gaps_seconds == []

    def test_gap_above_threshold_creates_new_session(self) -> None:
        """A gap of 31 minutes between two snapshot groups → two sessions."""
        session1 = [
            _snap(1, _ts(0), 0),
            _snap(2, _ts(5), 100),
            _snap(3, _ts(10), 200),
        ]
        session2 = [
            _snap(4, _ts(41), 200),  # 31-minute gap after snap 3
            _snap(5, _ts(46), 250),
        ]
        snaps = session1 + session2
        result = analyze_writing_process(snaps, session_gap_seconds=1800.0)
        assert result.session_count == 2
        assert len(result.sessions) == 2
        assert result.sessions[0].session_index == 0
        assert result.sessions[1].session_index == 1
        # One inter-session gap
        assert len(result.inter_session_gaps_seconds) == 1
        gap = result.inter_session_gaps_seconds[0]
        assert gap > 0

    def test_gap_exactly_at_threshold_creates_new_session(self) -> None:
        """A gap of exactly 30 minutes (= session_gap_seconds) → two sessions.

        The boundary is inclusive: gaps >= threshold open a new session.
        """
        session1 = [_snap(1, _ts(0), 0), _snap(2, _ts(5), 100)]
        # Exactly 30 minutes (1800 s) after snap 2 at t=5 min → snap 3 at t=35 min
        session2 = [_snap(3, _ts(35), 100), _snap(4, _ts(40), 150)]
        snaps = session1 + session2
        result = analyze_writing_process(snaps, session_gap_seconds=1800.0)
        assert result.session_count == 2
        assert len(result.inter_session_gaps_seconds) == 1

    def test_gap_one_second_below_threshold_stays_same_session(self) -> None:
        """A gap of 1799 s (< 1800 s threshold) stays in the same session."""
        # snap 1 at t=0, snap 2 at t=29min59s (1799 s gap)
        snaps = [_snap(1, _ts(0), 0), _snap(2, _ts(29.983), 100)]
        result = analyze_writing_process(snaps, session_gap_seconds=1800.0)
        assert result.session_count == 1

    def test_multiple_sessions_all_indexed_correctly(self) -> None:
        """Three sessions separated by long gaps."""
        s1 = [_snap(1, _ts(0), 0), _snap(2, _ts(5), 50)]
        s2 = [_snap(3, _ts(60), 50), _snap(4, _ts(65), 100)]
        s3 = [_snap(5, _ts(120), 100), _snap(6, _ts(125), 150)]
        snaps = s1 + s2 + s3
        result = analyze_writing_process(snaps, session_gap_seconds=1800.0)
        assert result.session_count == 3
        assert [s.session_index for s in result.sessions] == [0, 1, 2]
        assert len(result.inter_session_gaps_seconds) == 2

    def test_session_duration_computed_correctly(self) -> None:
        """Session spanning 10 minutes → duration_seconds = 600."""
        snaps = [
            _snap(1, _ts(0), 0),
            _snap(2, _ts(5), 50),
            _snap(3, _ts(10), 100),
        ]
        result = analyze_writing_process(snaps, session_gap_seconds=1800.0)
        assert result.session_count == 1
        assert result.sessions[0].duration_seconds == pytest.approx(600.0)

    def test_active_writing_seconds_is_sum_of_session_durations(self) -> None:
        """Two 10-minute sessions → active_writing_seconds = 1200."""
        s1 = [_snap(1, _ts(0), 0), _snap(2, _ts(10), 100)]
        s2 = [_snap(3, _ts(60), 100), _snap(4, _ts(70), 150)]
        snaps = s1 + s2
        result = analyze_writing_process(snaps, session_gap_seconds=1800.0)
        assert result.active_writing_seconds == pytest.approx(1200.0)

    def test_total_elapsed_seconds_spans_first_to_last(self) -> None:
        """Three snapshots over 30 minutes → total_elapsed = 1800s."""
        snaps = [_snap(1, _ts(0), 0), _snap(2, _ts(5), 50), _snap(3, _ts(30), 100)]
        result = analyze_writing_process(snaps, session_gap_seconds=1800.0)
        assert result.total_elapsed_seconds == pytest.approx(1800.0)

    def test_out_of_order_snapshots_sorted_correctly(self) -> None:
        """Snapshots submitted out of chronological order are sorted before processing."""
        snaps = [
            _snap(3, _ts(10), 100),
            _snap(1, _ts(0), 0),
            _snap(2, _ts(5), 50),
        ]
        result = analyze_writing_process(snaps, session_gap_seconds=1800.0)
        assert result.session_count == 1
        assert result.sessions[0].word_count_start == 0
        assert result.sessions[0].word_count_end == 100

    def test_duplicate_timestamps_handled_gracefully(self) -> None:
        """Duplicate timestamps are treated as same-moment activity (no crash)."""
        ts = _ts(0)
        snaps = [_snap(1, ts, 0), _snap(2, ts, 10), _snap(3, ts, 20)]
        result = analyze_writing_process(snaps)
        assert result.has_process_data is True
        assert result.session_count == 1


class TestPasteDetection:
    def test_large_delta_flags_paste_event(self) -> None:
        """200-word jump from 0 → 200 should trigger a paste event."""
        snaps = [
            _snap(1, _ts(0), 0),
            _snap(2, _ts(1), 200),
        ]
        result = analyze_writing_process(
            snaps,
            paste_min_words=50,
            paste_min_fraction=0.15,
        )
        assert len(result.paste_events) == 1
        evt = result.paste_events[0]
        assert evt.snapshot_seq == 2
        assert evt.words_before == 0
        assert evt.words_after == 200
        assert evt.words_added == 200

    def test_small_delta_does_not_flag_paste(self) -> None:
        """30-word jump is below threshold → no paste event."""
        snaps = [
            _snap(1, _ts(0), 100),
            _snap(2, _ts(1), 130),
        ]
        result = analyze_writing_process(
            snaps,
            paste_min_words=50,
            paste_min_fraction=0.15,
        )
        assert result.paste_events == []

    def test_large_absolute_but_small_fraction_no_paste(self) -> None:
        """60-word jump out of a 500-word essay is 12% — below 15% threshold."""
        snaps = [
            _snap(1, _ts(0), 440),
            _snap(2, _ts(1), 500),
        ]
        result = analyze_writing_process(
            snaps,
            paste_min_words=50,
            paste_min_fraction=0.15,
        )
        assert result.paste_events == []

    def test_multiple_paste_events_detected(self) -> None:
        """Two qualifying jumps → two paste events."""
        snaps = [
            _snap(1, _ts(0), 0),
            _snap(2, _ts(1), 200),   # jump 1
            _snap(3, _ts(2), 210),
            _snap(4, _ts(3), 410),   # jump 2
        ]
        result = analyze_writing_process(
            snaps,
            paste_min_words=50,
            paste_min_fraction=0.15,
        )
        assert len(result.paste_events) == 2

    def test_paste_event_session_index_assigned(self) -> None:
        """Paste event occurring in session 1 should carry session_index=1."""
        s1 = [_snap(1, _ts(0), 0), _snap(2, _ts(5), 10)]
        # Long gap, then second session with paste
        s2 = [_snap(3, _ts(60), 10), _snap(4, _ts(61), 300)]
        snaps = s1 + s2
        result = analyze_writing_process(
            snaps,
            session_gap_seconds=1800.0,
            paste_min_words=50,
            paste_min_fraction=0.1,
        )
        assert len(result.paste_events) == 1
        assert result.paste_events[0].session_index == 1

    def test_word_count_decrease_not_flagged_as_paste(self) -> None:
        """A net decrease in word count (deletion) is not a paste event."""
        snaps = [
            _snap(1, _ts(0), 300),
            _snap(2, _ts(1), 100),
        ]
        result = analyze_writing_process(
            snaps,
            paste_min_words=50,
            paste_min_fraction=0.15,
        )
        assert result.paste_events == []


class TestRapidCompletionDetection:
    def test_short_session_completing_most_of_essay_flagged(self) -> None:
        """Single 5-minute session adding 80% of final word count → rapid completion."""
        snaps = [
            _snap(1, _ts(0), 0),
            _snap(2, _ts(2.5), 200),
            _snap(3, _ts(5), 400),
        ]
        result = analyze_writing_process(
            snaps,
            rapid_completion_fraction=0.75,
            rapid_completion_max_seconds=1200.0,
        )
        assert len(result.rapid_completion_events) == 1
        evt = result.rapid_completion_events[0]
        assert evt.session_index == 0
        assert evt.completion_fraction == pytest.approx(1.0)

    def test_long_session_not_flagged(self) -> None:
        """Session lasting longer than threshold is not flagged as rapid completion."""
        snaps = [_snap(i + 1, _ts(i * 4), i * 50) for i in range(10)]  # ~36 min
        result = analyze_writing_process(
            snaps,
            rapid_completion_fraction=0.75,
            rapid_completion_max_seconds=1200.0,
        )
        assert result.rapid_completion_events == []

    def test_short_session_adding_small_fraction_not_flagged(self) -> None:
        """Short session adding only 30% of the final word count → not rapid completion."""
        snaps = [
            _snap(1, _ts(0), 0),
            _snap(2, _ts(5), 150),  # 150 / 500 = 30%
            # Big gap — second session
            _snap(3, _ts(60), 150),
            _snap(4, _ts(65), 500),
        ]
        result = analyze_writing_process(
            snaps,
            rapid_completion_fraction=0.75,
            rapid_completion_max_seconds=1200.0,
        )
        # First session: 30% → not flagged
        # Second session: 350/500 = 70% → not flagged (below 75%)
        assert result.rapid_completion_events == []

    def test_zero_final_word_count_no_rapid_completion(self) -> None:
        """Essay with zero final word count never triggers rapid completion."""
        snaps = [_snap(1, _ts(0), 0), _snap(2, _ts(1), 0)]
        result = analyze_writing_process(snaps, rapid_completion_fraction=0.75)
        assert result.rapid_completion_events == []

    def test_rapid_completion_fraction_in_response(self) -> None:
        """completion_fraction reflects how much of the final essay was written."""
        snaps = [
            _snap(1, _ts(0), 0),
            _snap(2, _ts(5), 500),
        ]
        result = analyze_writing_process(
            snaps,
            rapid_completion_fraction=0.75,
            rapid_completion_max_seconds=1200.0,
        )
        assert len(result.rapid_completion_events) == 1
        assert result.rapid_completion_events[0].completion_fraction == pytest.approx(1.0)


class TestSparsyNoisySequences:
    def test_snapshot_with_unparseable_ts_skipped(self) -> None:
        """Snapshots with invalid timestamps are skipped; valid ones still processed."""
        snaps = [
            {"seq": 1, "ts": "NOT-A-DATE", "word_count": 100},
            _snap(2, _ts(5), 200),
        ]
        result = analyze_writing_process(snaps)
        assert result.has_process_data is True
        assert result.session_count == 1
        assert result.sessions[0].word_count_start == 200

    def test_snapshot_with_missing_key_skipped(self) -> None:
        """Snapshots missing required keys are silently skipped."""
        snaps = [
            {"seq": 1, "ts": _ts(0).isoformat()},  # missing word_count
            _snap(2, _ts(5), 100),
        ]
        result = analyze_writing_process(snaps)
        assert result.has_process_data is True
        assert result.session_count == 1

    def test_snapshot_with_negative_word_count_clamped_to_zero(self) -> None:
        """Negative word counts are clamped to 0 rather than propagating."""
        snaps = [
            {"seq": 1, "ts": _ts(0).isoformat(), "word_count": -50},
            _snap(2, _ts(5), 100),
        ]
        result = analyze_writing_process(snaps)
        assert result.has_process_data is True
        # First snapshot word_count clamped to 0
        assert result.sessions[0].word_count_start == 0

    def test_very_long_sequence_handled(self) -> None:
        """500 snapshots processed without error."""
        snaps = [_snap(i + 1, _ts(i * 0.25), i * 2) for i in range(500)]
        result = analyze_writing_process(snaps)
        assert result.has_process_data is True
        assert result.session_count >= 1

    def test_naive_ts_treated_as_utc(self) -> None:
        """Timestamps without timezone info are treated as UTC."""
        naive_ts = datetime(2026, 4, 1, 10, 0, 0)  # no tzinfo
        snaps = [{"seq": 1, "ts": naive_ts.isoformat(), "word_count": 100}]
        result = analyze_writing_process(snaps)
        assert result.has_process_data is True


# ---------------------------------------------------------------------------
# TestGetProcessSignalsService — service layer (mocked DB)
# ---------------------------------------------------------------------------


def _make_teacher(teacher_id: uuid.UUID | None = None) -> MagicMock:
    t = MagicMock()
    t.id = teacher_id or uuid.uuid4()
    return t


def _make_version(
    version_id: uuid.UUID | None = None,
    essay_id: uuid.UUID | None = None,
    writing_snapshots: list[Any] | None = None,
    process_signals: dict[str, Any] | None = None,
    word_count: int = 100,
) -> MagicMock:
    v = MagicMock()
    v.id = version_id or uuid.uuid4()
    v.essay_id = essay_id or uuid.uuid4()
    v.word_count = word_count
    v.writing_snapshots = writing_snapshots
    v.process_signals = process_signals
    v.submitted_at = datetime.now(UTC)
    return v


class TestGetProcessSignalsService:
    @pytest.mark.asyncio
    async def test_computes_and_caches_signals_on_first_call(self) -> None:
        """First request computes signals and persists them to process_signals."""
        from app.services.essay import get_process_signals

        teacher_id = uuid.uuid4()
        essay_id = uuid.uuid4()
        version_id = uuid.uuid4()

        snaps = [
            _snap(1, _ts(0), 0),
            _snap(2, _ts(5), 100),
        ]
        version = _make_version(
            version_id=version_id,
            essay_id=essay_id,
            writing_snapshots=snaps,
            process_signals=None,
        )

        scalar_mock = MagicMock()
        scalar_mock.scalar_one_or_none.return_value = version

        db = MagicMock()
        db.execute = AsyncMock(return_value=scalar_mock)
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        result = await get_process_signals(db=db, teacher_id=teacher_id, essay_id=essay_id)

        # Should have been committed (cache stored)
        db.commit.assert_awaited_once()
        assert result.essay_id == essay_id
        assert result.essay_version_id == version_id
        assert result.has_process_data is True
        assert result.session_count >= 1

    @pytest.mark.asyncio
    async def test_returns_cached_result_on_second_call(self) -> None:
        """If process_signals cache is current (snapshot_count matches), no recompute."""
        from app.services.essay import get_process_signals

        teacher_id = uuid.uuid4()
        essay_id = uuid.uuid4()
        version_id = uuid.uuid4()

        snaps = [_snap(1, _ts(0), 100)]
        # Pre-populate cache with matching snapshot_count
        cached_payload: dict[str, Any] = {
            "snapshot_count": 1,
            "computed_at": _ts(1).isoformat(),
            "has_process_data": True,
            "session_count": 1,
            "active_writing_seconds": 0.0,
            "total_elapsed_seconds": 0.0,
            "inter_session_gaps_seconds": [],
            "sessions": [
                {
                    "session_index": 0,
                    "started_at": _ts(0).isoformat(),
                    "ended_at": _ts(0).isoformat(),
                    "duration_seconds": 0.0,
                    "snapshot_count": 1,
                    "word_count_start": 100,
                    "word_count_end": 100,
                    "words_added": 0,
                }
            ],
            "paste_events": [],
            "rapid_completion_events": [],
        }
        version = _make_version(
            version_id=version_id,
            essay_id=essay_id,
            writing_snapshots=snaps,
            process_signals=cached_payload,
        )

        scalar_mock = MagicMock()
        scalar_mock.scalar_one_or_none.return_value = version

        db = MagicMock()
        db.execute = AsyncMock(return_value=scalar_mock)
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        result = await get_process_signals(db=db, teacher_id=teacher_id, essay_id=essay_id)

        # No commit — cache is still valid
        db.commit.assert_not_awaited()
        assert result.session_count == 1

    @pytest.mark.asyncio
    async def test_invalidates_cache_when_new_snapshots_added(self) -> None:
        """If snapshot_count in cache < current, signals are recomputed."""
        from app.services.essay import get_process_signals

        teacher_id = uuid.uuid4()
        essay_id = uuid.uuid4()
        version_id = uuid.uuid4()

        snaps = [_snap(1, _ts(0), 0), _snap(2, _ts(5), 100)]
        # Cache says snapshot_count=1 but version now has 2
        stale_payload: dict[str, Any] = {
            "snapshot_count": 1,
            "computed_at": _ts(0).isoformat(),
            "has_process_data": True,
            "session_count": 1,
            "active_writing_seconds": 0.0,
            "total_elapsed_seconds": 0.0,
            "inter_session_gaps_seconds": [],
            "sessions": [],
            "paste_events": [],
            "rapid_completion_events": [],
        }
        version = _make_version(
            version_id=version_id,
            essay_id=essay_id,
            writing_snapshots=snaps,
            process_signals=stale_payload,
        )

        scalar_mock = MagicMock()
        scalar_mock.scalar_one_or_none.return_value = version

        db = MagicMock()
        db.execute = AsyncMock(return_value=scalar_mock)
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        result = await get_process_signals(db=db, teacher_id=teacher_id, essay_id=essay_id)

        # Recomputed → commit called
        db.commit.assert_awaited_once()
        assert result.has_process_data is True

    @pytest.mark.asyncio
    async def test_file_upload_essay_returns_no_process_data(self) -> None:
        """Essays with writing_snapshots=None return has_process_data=False."""
        from app.services.essay import get_process_signals

        teacher_id = uuid.uuid4()
        essay_id = uuid.uuid4()
        version_id = uuid.uuid4()

        version = _make_version(
            version_id=version_id,
            essay_id=essay_id,
            writing_snapshots=None,  # file-upload essay
            process_signals=None,
        )

        scalar_mock = MagicMock()
        scalar_mock.scalar_one_or_none.return_value = version

        db = MagicMock()
        db.execute = AsyncMock(return_value=scalar_mock)
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        result = await get_process_signals(db=db, teacher_id=teacher_id, essay_id=essay_id)

        # File-upload essays have no process data — signals still computed and cached
        assert result.has_process_data is False
        assert result.session_count == 0
        assert result.sessions == []

    @pytest.mark.asyncio
    async def test_cross_teacher_raises_forbidden(self) -> None:
        """Version not found → _get_essay_for_teacher raises ForbiddenError."""
        from app.services.essay import get_process_signals

        scalar_mock = MagicMock()
        scalar_mock.scalar_one_or_none.return_value = None  # not found in JOIN

        db = MagicMock()
        db.execute = AsyncMock(return_value=scalar_mock)

        with patch(
            "app.services.essay._get_essay_for_teacher",
            new=AsyncMock(side_effect=ForbiddenError("forbidden")),
        ), pytest.raises(ForbiddenError):
            await get_process_signals(
                db=db,
                teacher_id=uuid.uuid4(),
                essay_id=uuid.uuid4(),
            )

    @pytest.mark.asyncio
    async def test_essay_not_found_raises_not_found(self) -> None:
        """Version not found + essay not found → NotFoundError."""
        from app.services.essay import get_process_signals

        scalar_mock = MagicMock()
        scalar_mock.scalar_one_or_none.return_value = None

        db = MagicMock()
        db.execute = AsyncMock(return_value=scalar_mock)

        with patch(
            "app.services.essay._get_essay_for_teacher",
            new=AsyncMock(side_effect=NotFoundError("not found")),
        ), pytest.raises(NotFoundError):
            await get_process_signals(
                db=db,
                teacher_id=uuid.uuid4(),
                essay_id=uuid.uuid4(),
            )


# ---------------------------------------------------------------------------
# TestProcessSignalsEndpoint — HTTP layer
# ---------------------------------------------------------------------------


def _make_teacher_mock(teacher_id: uuid.UUID | None = None) -> MagicMock:
    t = MagicMock()
    t.id = teacher_id or uuid.uuid4()
    t.email = "teacher@school.edu"
    t.email_verified = True
    return t


def _app_with_teacher(teacher: MagicMock | None = None) -> Any:
    teacher = teacher or _make_teacher_mock()
    app = create_app()
    app.dependency_overrides[get_current_teacher] = lambda: teacher  # type: ignore[attr-defined]
    mock_db = MagicMock()
    mock_db.commit = AsyncMock()

    async def _mock_get_db() -> AsyncGenerator[MagicMock, None]:
        yield mock_db

    app.dependency_overrides[get_db] = _mock_get_db  # type: ignore[attr-defined]
    return app


class TestProcessSignalsEndpoint:
    def _minimal_signals_payload(
        self,
        essay_id: uuid.UUID,
        version_id: uuid.UUID,
    ) -> dict[str, Any]:
        """Build a minimal ProcessSignalsResponse-compatible dict."""
        from app.schemas.essay import ProcessSignalsResponse

        return ProcessSignalsResponse(
            essay_id=essay_id,
            essay_version_id=version_id,
            has_process_data=True,
            session_count=1,
            sessions=[],
            inter_session_gaps_seconds=[],
            active_writing_seconds=300.0,
            total_elapsed_seconds=300.0,
            paste_events=[],
            rapid_completion_events=[],
            computed_at=datetime.now(UTC),
        )

    def test_200_returns_signals(self) -> None:
        essay_id = uuid.uuid4()
        version_id = uuid.uuid4()
        payload = self._minimal_signals_payload(essay_id, version_id)

        app = _app_with_teacher()
        with (
            patch(
                "app.routers.essays.get_process_signals",
                new=AsyncMock(return_value=payload),
            ),
            TestClient(app) as client,
        ):
            resp = client.get(f"/api/v1/essays/{essay_id}/process-signals")

        assert resp.status_code == 200
        body = resp.json()
        assert "data" in body
        assert body["data"]["has_process_data"] is True
        assert body["data"]["session_count"] == 1

    def test_401_when_no_auth(self) -> None:
        essay_id = uuid.uuid4()
        app = create_app()
        # No dependency override — get_current_teacher will raise UnauthorizedError
        from app.exceptions import UnauthorizedError

        app.dependency_overrides[get_current_teacher] = lambda: (_ for _ in ()).throw(
            UnauthorizedError("no auth")
        )
        with TestClient(app) as client:
            resp = client.get(f"/api/v1/essays/{essay_id}/process-signals")
        assert resp.status_code == 401

    def test_403_when_cross_teacher(self) -> None:
        essay_id = uuid.uuid4()
        app = _app_with_teacher()
        with (
            patch(
                "app.routers.essays.get_process_signals",
                new=AsyncMock(side_effect=ForbiddenError("forbidden")),
            ),
            TestClient(app) as client,
        ):
            resp = client.get(f"/api/v1/essays/{essay_id}/process-signals")
        assert resp.status_code == 403

    def test_404_when_essay_not_found(self) -> None:
        essay_id = uuid.uuid4()
        app = _app_with_teacher()
        with (
            patch(
                "app.routers.essays.get_process_signals",
                new=AsyncMock(side_effect=NotFoundError("not found")),
            ),
            TestClient(app) as client,
        ):
            resp = client.get(f"/api/v1/essays/{essay_id}/process-signals")
        assert resp.status_code == 404

    def test_response_envelope_shape(self) -> None:
        """Response must be wrapped in {"data": ...} — never a bare JSON object."""
        essay_id = uuid.uuid4()
        version_id = uuid.uuid4()
        payload = self._minimal_signals_payload(essay_id, version_id)

        app = _app_with_teacher()
        with (
            patch(
                "app.routers.essays.get_process_signals",
                new=AsyncMock(return_value=payload),
            ),
            TestClient(app) as client,
        ):
            resp = client.get(f"/api/v1/essays/{essay_id}/process-signals")

        body = resp.json()
        assert list(body.keys()) == ["data"]
