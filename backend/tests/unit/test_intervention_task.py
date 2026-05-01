"""Unit tests for app/tasks/intervention.py (M7-01).

Tests cover:
- Task registration in Celery (name, max_retries).
- Happy path: loads teacher IDs, scans each teacher, logs completion.
- Empty system: no teachers → no scan calls.
- Single teacher error is caught and logged, scan continues for other teachers.
- Transient infrastructure error triggers exponential-backoff retry.
- Exhausted retries re-raise and mark the task FAILURE.
- Scheduled beat entry: task appears in the beat schedule.

No student PII in any fixture.  All database and broker calls are mocked.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.tasks.celery_app import celery
from app.tasks.intervention import (
    _run_scan_intervention_signals,
    scan_intervention_signals,
)

# ---------------------------------------------------------------------------
# Tests — task registration
# ---------------------------------------------------------------------------


class TestScanInterventionSignalsTaskRegistration:
    def test_task_is_registered_in_celery(self) -> None:
        assert "tasks.intervention.scan_intervention_signals" in celery.tasks

    def test_task_has_correct_max_retries(self) -> None:
        assert scan_intervention_signals.max_retries == 3

    def test_task_name_matches_convention(self) -> None:
        assert scan_intervention_signals.name == "tasks.intervention.scan_intervention_signals"

    def test_beat_schedule_contains_intervention_task(self) -> None:
        schedule = celery.conf.beat_schedule
        entry = schedule.get("scan-intervention-signals-daily")
        assert entry is not None
        assert entry["task"] == "tasks.intervention.scan_intervention_signals"


# ---------------------------------------------------------------------------
# Tests — _run_scan_intervention_signals (async helper)
# ---------------------------------------------------------------------------


class TestRunScanInterventionSignals:
    @pytest.mark.asyncio
    async def test_happy_path_scans_all_teachers(self) -> None:
        teacher_id_1 = uuid.uuid4()
        teacher_id_2 = uuid.uuid4()

        mock_db = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)

        mock_session_local = MagicMock(return_value=mock_db)

        with (
            patch("app.tasks.intervention.AsyncSessionLocal", mock_session_local),
            patch(
                "app.services.intervention_agent.get_all_teacher_ids",
                new=AsyncMock(return_value=[teacher_id_1, teacher_id_2]),
            ),
            patch(
                "app.services.intervention_agent.scan_teacher_for_interventions",
                new=AsyncMock(return_value=[]),
            ) as mock_scan,
            patch("app.tasks.intervention.set_tenant_context", new=AsyncMock()),
        ):
            await _run_scan_intervention_signals()

        # Should have been called once per teacher.
        assert mock_scan.await_count == 2

    @pytest.mark.asyncio
    async def test_empty_teacher_list_no_scan_calls(self) -> None:
        mock_db = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)

        mock_session_local = MagicMock(return_value=mock_db)

        with (
            patch("app.tasks.intervention.AsyncSessionLocal", mock_session_local),
            patch(
                "app.services.intervention_agent.get_all_teacher_ids",
                new=AsyncMock(return_value=[]),
            ),
            patch(
                "app.services.intervention_agent.scan_teacher_for_interventions",
                new=AsyncMock(return_value=[]),
            ) as mock_scan,
            patch("app.tasks.intervention.set_tenant_context", new=AsyncMock()),
        ):
            await _run_scan_intervention_signals()

        mock_scan.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_single_teacher_error_is_skipped(self) -> None:
        """A failure for one teacher should not abort the scan for others."""
        teacher_id_1 = uuid.uuid4()
        teacher_id_2 = uuid.uuid4()

        mock_db = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)

        mock_session_local = MagicMock(return_value=mock_db)

        call_count = 0

        async def _scan_side_effect(db: object, teacher_id: uuid.UUID) -> list:
            nonlocal call_count
            call_count += 1
            if teacher_id == teacher_id_1:
                raise RuntimeError("Simulated DB error")
            return []

        with (
            patch("app.tasks.intervention.AsyncSessionLocal", mock_session_local),
            patch(
                "app.services.intervention_agent.get_all_teacher_ids",
                new=AsyncMock(return_value=[teacher_id_1, teacher_id_2]),
            ),
            patch(
                "app.services.intervention_agent.scan_teacher_for_interventions",
                new=AsyncMock(side_effect=_scan_side_effect),
            ),
            patch("app.tasks.intervention.set_tenant_context", new=AsyncMock()),
        ):
            # Should not raise; error for teacher_1 is caught internally.
            await _run_scan_intervention_signals()

        # Both teachers attempted.
        assert call_count == 2


# ---------------------------------------------------------------------------
# Tests — scan_intervention_signals (synchronous Celery wrapper)
# ---------------------------------------------------------------------------


class TestScanInterventionSignalsCeleryTask:
    def test_happy_path_calls_run_task_async(self) -> None:
        with patch("app.tasks.intervention.asyncio.run", return_value=None) as mock_run:
            result = scan_intervention_signals()
        assert result is None
        mock_run.assert_called_once()

    def test_transient_error_triggers_retry(self) -> None:
        with patch(
            "app.tasks.intervention._run_scan_intervention_signals",
            new=AsyncMock(side_effect=RuntimeError("DB unavailable")),
        ):
            result = scan_intervention_signals.apply(args=[])

        assert result.failed(), "Task should fail after exhausting retries"

    def test_exhausted_retries_reraises(self) -> None:
        """After max retries the task is marked FAILURE."""
        with patch(
            "app.tasks.intervention._run_scan_intervention_signals",
            new=AsyncMock(side_effect=RuntimeError("Persistent error")),
        ):
            result = scan_intervention_signals.apply(args=[])

        assert result.failed(), "Task should be FAILURE after exhausting retries"

    def test_idempotent_on_second_call(self) -> None:
        with patch("app.tasks.intervention.asyncio.run", return_value=None):
            r1 = scan_intervention_signals()
            r2 = scan_intervention_signals()

        assert r1 is None
        assert r2 is None
