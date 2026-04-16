"""Unit tests for app.tasks.celery_app and app.tasks.debug.

All tests run without a real Redis broker.  Tasks are executed
synchronously via ``task.apply()``, which runs the task in-process
without requiring a broker or a running worker.
"""

import pytest
from celery import Celery

from app.config import settings
from app.tasks.celery_app import celery
from app.tasks.debug import ping

# ---------------------------------------------------------------------------
# Celery app configuration
# ---------------------------------------------------------------------------


class TestCeleryAppConfiguration:
    def test_celery_is_celery_instance(self) -> None:
        assert isinstance(celery, Celery)

    def test_celery_app_name(self) -> None:
        assert celery.main == "rubric_grading_engine"

    def test_broker_url_from_settings(self) -> None:
        assert celery.conf.broker_url == settings.celery_broker_url

    def test_result_backend_from_settings(self) -> None:
        assert celery.conf.result_backend == settings.celery_result_backend

    def test_task_serializer_is_json(self) -> None:
        assert celery.conf.task_serializer == "json"

    def test_result_serializer_is_json(self) -> None:
        assert celery.conf.result_serializer == "json"

    def test_accept_content_is_json(self) -> None:
        assert "json" in celery.conf.accept_content

    def test_timezone_is_utc(self) -> None:
        assert celery.conf.timezone == "UTC"

    def test_enable_utc(self) -> None:
        assert celery.conf.enable_utc is True

    def test_debug_task_is_registered(self) -> None:
        assert "tasks.debug.ping" in celery.tasks

    def test_result_expires_from_settings(self) -> None:
        assert celery.conf.result_expires == settings.celery_result_expires_seconds


# ---------------------------------------------------------------------------
# ping task — eager execution (no broker required)
# ---------------------------------------------------------------------------


class TestPingTask:
    def test_ping_returns_message(self) -> None:
        value = ping.apply(args=["hello"]).get()
        assert value == "hello", f"Expected 'hello', got {value!r}"

    def test_ping_returns_empty_string(self) -> None:
        result = ping.apply(args=[""])
        assert result.get() == ""

    def test_ping_returns_arbitrary_string(self) -> None:
        msg = "smoke test 1234 !@#"
        result = ping.apply(args=[msg])
        assert result.get() == msg

    def test_ping_task_name(self) -> None:
        assert ping.name == "tasks.debug.ping"

    @pytest.mark.parametrize("message", ["hello", "world", "ping pong", "test 123"])
    def test_ping_parametrized(self, message: str) -> None:
        result = ping.apply(args=[message])
        assert result.get() == message
