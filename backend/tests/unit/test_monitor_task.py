"""Unit tests for app.tasks.monitor.

Verifies that:
- ``report_queue_metrics`` emits structured ``celery.queue_depth`` log events
  for each monitored queue.
- Depth values are non-negative integers.
- Errors are caught and logged without propagating.
- No student PII or credential-format strings appear in any log output.

Security:
- No student PII in fixtures.
- No credential-format strings.
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import pytest

from app.tasks.monitor import _MONITORED_QUEUES, _sample_queues, report_queue_metrics

# ---------------------------------------------------------------------------
# _MONITORED_QUEUES configuration
# ---------------------------------------------------------------------------


class TestMonitoredQueuesConfig:
    def test_monitored_queues_is_non_empty(self) -> None:
        assert len(_MONITORED_QUEUES) > 0, "At least one queue must be monitored"

    def test_default_celery_queue_is_monitored(self) -> None:
        assert "celery" in _MONITORED_QUEUES, (
            "'celery' (the Celery default queue) must always be monitored"
        )

    def test_monitoring_queue_is_monitored(self) -> None:
        """The dedicated monitor queue must itself be monitored."""
        assert "monitoring" in _MONITORED_QUEUES, (
            "'monitoring' queue must be included so its own depth is visible"
        )


# ---------------------------------------------------------------------------
# _sample_queues — internal helper
# ---------------------------------------------------------------------------


class TestSampleQueues:
    def test_returns_dict_with_queue_names(self) -> None:
        mock_redis = MagicMock()
        mock_redis.__enter__ = MagicMock(return_value=mock_redis)
        mock_redis.__exit__ = MagicMock(return_value=False)
        mock_redis.llen.return_value = 5

        with patch("redis.Redis.from_url", return_value=mock_redis):
            result = _sample_queues()

        assert isinstance(result, dict), f"Expected dict, got {type(result)}"
        for queue in _MONITORED_QUEUES:
            assert queue in result, f"Queue '{queue}' missing from result"

    def test_depth_values_are_integers(self) -> None:
        mock_redis = MagicMock()
        mock_redis.__enter__ = MagicMock(return_value=mock_redis)
        mock_redis.__exit__ = MagicMock(return_value=False)
        mock_redis.llen.return_value = 3

        with patch("redis.Redis.from_url", return_value=mock_redis):
            result = _sample_queues()

        for queue, depth in result.items():
            assert isinstance(depth, int), (
                f"Depth for queue '{queue}' must be int, got {type(depth)}"
            )

    def test_depth_is_non_negative(self) -> None:
        mock_redis = MagicMock()
        mock_redis.__enter__ = MagicMock(return_value=mock_redis)
        mock_redis.__exit__ = MagicMock(return_value=False)
        mock_redis.llen.return_value = 0

        with patch("redis.Redis.from_url", return_value=mock_redis):
            result = _sample_queues()

        for queue, depth in result.items():
            assert depth >= 0, f"Depth for queue '{queue}' must be >= 0, got {depth}"

    def test_emits_queue_depth_log_event(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        mock_redis = MagicMock()
        mock_redis.__enter__ = MagicMock(return_value=mock_redis)
        mock_redis.__exit__ = MagicMock(return_value=False)
        mock_redis.llen.return_value = 7

        with (
            patch("redis.Redis.from_url", return_value=mock_redis),
            caplog.at_level(logging.INFO, logger="app.tasks.monitor"),
        ):
            _sample_queues()

        events = [
            r for r in caplog.records
            if getattr(r, "event", None) == "celery.queue_depth"
        ]
        assert len(events) == len(_MONITORED_QUEUES), (
            f"Expected {len(_MONITORED_QUEUES)} queue_depth events, got {len(events)}"
        )

    def test_log_event_contains_queue_and_depth(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        mock_redis = MagicMock()
        mock_redis.__enter__ = MagicMock(return_value=mock_redis)
        mock_redis.__exit__ = MagicMock(return_value=False)
        mock_redis.llen.return_value = 12

        with (
            patch("redis.Redis.from_url", return_value=mock_redis),
            caplog.at_level(logging.INFO, logger="app.tasks.monitor"),
        ):
            _sample_queues()

        events = [
            r for r in caplog.records
            if getattr(r, "event", None) == "celery.queue_depth"
        ]
        assert events, "No celery.queue_depth event emitted"
        first = events[0]
        assert hasattr(first, "queue"), "Log event missing 'queue' field"
        assert hasattr(first, "depth"), "Log event missing 'depth' field"
        assert first.depth == 12  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# report_queue_metrics — Celery task entry point
# ---------------------------------------------------------------------------


class TestReportQueueMetricsTask:
    def test_returns_dict_on_success(self) -> None:
        mock_redis = MagicMock()
        mock_redis.__enter__ = MagicMock(return_value=mock_redis)
        mock_redis.__exit__ = MagicMock(return_value=False)
        mock_redis.llen.return_value = 0

        with patch("redis.Redis.from_url", return_value=mock_redis):
            result = report_queue_metrics.run()  # .run() bypasses Celery broker

        assert isinstance(result, dict), f"Expected dict, got {type(result)}"

    def test_returns_empty_dict_on_redis_error(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        with (
            patch("redis.Redis.from_url", side_effect=ConnectionError("redis unreachable")),
            caplog.at_level(logging.ERROR, logger="app.tasks.monitor"),
        ):
            result = report_queue_metrics.run()

        assert result == {}, f"Expected empty dict on error, got {result!r}"

    def test_logs_error_event_on_redis_failure(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        with (
            patch("redis.Redis.from_url", side_effect=ConnectionError("redis unreachable")),
            caplog.at_level(logging.ERROR, logger="app.tasks.monitor"),
        ):
            report_queue_metrics.run()

        error_events = [
            r for r in caplog.records
            if getattr(r, "event", None) == "celery.queue_monitor_error"
        ]
        assert error_events, "Expected a celery.queue_monitor_error log event on failure"

    def test_error_log_contains_error_type_not_message(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Error log must use error_type, never the exception message (may contain PII)."""
        sensitive_message = "redis://user:secret-password@host:6379"
        with (
            patch("redis.Redis.from_url", side_effect=ConnectionError(sensitive_message)),
            caplog.at_level(logging.ERROR, logger="app.tasks.monitor"),
        ):
            report_queue_metrics.run()

        for record in caplog.records:
            assert sensitive_message not in record.getMessage(), (
                f"Sensitive value leaked into log message: {record.getMessage()!r}"
            )

    def test_task_is_registered_in_celery(self) -> None:
        from app.tasks.celery_app import celery

        assert "tasks.monitor.report_queue_metrics" in celery.tasks, (
            "report_queue_metrics must be registered in the Celery app"
        )

    def test_beat_schedule_includes_queue_metrics(self) -> None:
        from app.tasks.celery_app import celery

        schedule = celery.conf.beat_schedule
        assert "report-queue-metrics-every-minute" in schedule, (
            "Beat schedule must include 'report-queue-metrics-every-minute'"
        )

    def test_beat_schedule_runs_every_60_seconds(self) -> None:
        from app.tasks.celery_app import celery

        entry = celery.conf.beat_schedule.get("report-queue-metrics-every-minute", {})
        assert entry.get("schedule") == 60.0, (
            f"Queue metrics should run every 60s, got {entry.get('schedule')!r}"
        )

    def test_beat_schedule_entry_has_expires(self) -> None:
        """Beat entry must discard stale tasks that pile up during queue saturation."""
        from app.tasks.celery_app import celery

        entry = celery.conf.beat_schedule.get("report-queue-metrics-every-minute", {})
        options = entry.get("options", {})
        assert "expires" in options, "Beat entry must set 'expires' to discard stale samples"
        assert options["expires"] < 60, (
            f"Expires ({options['expires']}) must be less than the 60 s schedule interval"
        )

    def test_monitor_task_routes_to_monitoring_queue(self) -> None:
        """Monitor task must be routed to a dedicated queue, not the default 'celery' queue."""
        from app.tasks.celery_app import celery

        routes = celery.conf.task_routes or {}
        route = routes.get("tasks.monitor.report_queue_metrics", {})
        assert route.get("queue") == "monitoring", (
            "report_queue_metrics must route to 'monitoring' queue to avoid "
            "blocking behind the queue it is measuring"
        )
