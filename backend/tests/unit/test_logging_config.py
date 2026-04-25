"""Unit tests for structured JSON logging configuration.

Covers:
- JsonFormatter: verifies that every log line is valid JSON and contains
  the required fixed fields (timestamp, level, logger, service,
  correlation_id, message).
- CorrelationIdFilter: verifies that the per-request correlation ID is
  injected into log records from the ContextVar.
- PII safety: verifies that exception messages (which may contain student PII)
  are never included in the JSON output — only the exception type name.
- configure_logging: smoke-test that the function runs without error and
  installs the expected handler/formatter.
"""

from __future__ import annotations

import json
import logging

import pytest

from app.logging_config import (
    CorrelationIdFilter,
    JsonFormatter,
    _iso_timestamp,
    configure_logging,
    correlation_id_var,
)

# ---------------------------------------------------------------------------
# JsonFormatter — field presence
# ---------------------------------------------------------------------------


class TestJsonFormatterFields:
    """Every log line must carry the documented fixed fields."""

    @pytest.fixture()
    def formatter(self) -> JsonFormatter:
        fmt = JsonFormatter()
        return fmt

    def _make_record(
        self,
        msg: str = "test message",
        level: int = logging.INFO,
        name: str = "app.test",
    ) -> logging.LogRecord:
        record = logging.LogRecord(
            name=name,
            level=level,
            pathname="test.py",
            lineno=1,
            msg=msg,
            args=(),
            exc_info=None,
        )
        # Simulate CorrelationIdFilter having run (adds the attribute).
        record.correlation_id = ""  # type: ignore[attr-defined]
        return record

    def test_output_is_valid_json(self, formatter: JsonFormatter) -> None:
        record = self._make_record()
        output = formatter.format(record)
        parsed = json.loads(output)  # must not raise
        assert isinstance(parsed, dict)

    def test_timestamp_field_present(self, formatter: JsonFormatter) -> None:
        output = json.loads(formatter.format(self._make_record()))
        assert "timestamp" in output

    def test_timestamp_is_iso8601(self, formatter: JsonFormatter) -> None:
        output = json.loads(formatter.format(self._make_record()))
        ts = output["timestamp"]
        # Basic ISO-8601 UTC shape: "YYYY-MM-DDTHH:MM:SS.mmmZ"
        assert ts.endswith("Z"), f"Expected UTC timestamp ending in 'Z': {ts!r}"
        assert "T" in ts, f"Expected 'T' separator in ISO timestamp: {ts!r}"

    def test_level_field_present(self, formatter: JsonFormatter) -> None:
        output = json.loads(formatter.format(self._make_record(level=logging.WARNING)))
        assert output["level"] == "WARNING"

    def test_logger_field_present(self, formatter: JsonFormatter) -> None:
        output = json.loads(formatter.format(self._make_record(name="app.services.grading")))
        assert output["logger"] == "app.services.grading"

    def test_service_field_is_rubric_grading_engine(self, formatter: JsonFormatter) -> None:
        output = json.loads(formatter.format(self._make_record()))
        assert output["service"] == "rubric-grading-engine"

    def test_correlation_id_field_present(self, formatter: JsonFormatter) -> None:
        output = json.loads(formatter.format(self._make_record()))
        assert "correlation_id" in output

    def test_message_field_present(self, formatter: JsonFormatter) -> None:
        output = json.loads(formatter.format(self._make_record(msg="hello world")))
        assert output["message"] == "hello world"


# ---------------------------------------------------------------------------
# JsonFormatter — extra fields
# ---------------------------------------------------------------------------


class TestJsonFormatterExtraFields:
    """Extra fields passed via ``extra=`` must appear in the JSON payload."""

    @pytest.fixture()
    def formatter(self) -> JsonFormatter:
        return JsonFormatter()

    def test_extra_entity_id_is_included(self, formatter: JsonFormatter) -> None:
        record = logging.LogRecord(
            name="app.grading",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="grading started",
            args=(),
            exc_info=None,
        )
        record.essay_id = "550e8400-e29b-41d4-a716-446655440000"  # type: ignore[attr-defined]
        record.correlation_id = ""  # type: ignore[attr-defined]

        output = json.loads(formatter.format(record))
        assert output.get("essay_id") == "550e8400-e29b-41d4-a716-446655440000"

    def test_error_type_field_is_included(self, formatter: JsonFormatter) -> None:
        record = logging.LogRecord(
            name="app.tasks.grading",
            level=logging.ERROR,
            pathname="test.py",
            lineno=1,
            msg="task failed",
            args=(),
            exc_info=None,
        )
        record.error_type = "LLMError"  # type: ignore[attr-defined]
        record.correlation_id = ""  # type: ignore[attr-defined]

        output = json.loads(formatter.format(record))
        assert output.get("error_type") == "LLMError"

    def test_reserved_fields_cannot_be_overwritten_by_extra(self, formatter: JsonFormatter) -> None:
        """Fixed output fields must not be overrideable via extra= kwargs."""
        record = logging.LogRecord(
            name="app.test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="real message",
            args=(),
            exc_info=None,
        )
        # Simulate a caller passing reserved field names via extra=.
        record.timestamp = "1970-01-01T00:00:00.000Z"  # type: ignore[attr-defined]
        record.level = "FAKE"  # type: ignore[attr-defined]
        record.logger = "attacker.module"  # type: ignore[attr-defined]
        record.service = "evil-service"  # type: ignore[attr-defined]
        record.correlation_id = ""  # type: ignore[attr-defined]

        output = json.loads(formatter.format(record))
        # Fixed fields must reflect the real LogRecord values, not extra= overrides.
        assert output["level"] == "INFO"
        assert output["logger"] == "app.test"
        assert output["service"] == "rubric-grading-engine"
        assert output["message"] == "real message"
        assert output["timestamp"] != "1970-01-01T00:00:00.000Z"


# ---------------------------------------------------------------------------
# JsonFormatter — PII safety (exception messages never in output)
# ---------------------------------------------------------------------------


class TestJsonFormatterPIISafety:
    """Exception messages must never appear in the JSON output.

    Exception messages can contain student PII (e.g. from database errors
    that echo query parameters, or from LLM responses that include essay text).
    Only the exception *type* name is safe to log.
    """

    @pytest.fixture()
    def formatter(self) -> JsonFormatter:
        return JsonFormatter()

    def _make_exc_record(
        self,
        msg: str,
        exc: BaseException,
    ) -> logging.LogRecord:
        try:
            raise exc
        except type(exc):
            import sys

            exc_info = sys.exc_info()

        record = logging.LogRecord(
            name="app.test",
            level=logging.ERROR,
            pathname="test.py",
            lineno=1,
            msg=msg,
            args=(),
            exc_info=exc_info,
        )
        record.correlation_id = ""  # type: ignore[attr-defined]
        return record

    def test_exception_message_is_not_in_output(self, formatter: JsonFormatter) -> None:
        pii_message = "essay submitted by <student_name> contained invalid content"
        record = self._make_exc_record("an error occurred", ValueError(pii_message))
        output = formatter.format(record)
        assert pii_message not in output, f"PII found in log output: {output!r}"

    def test_exception_type_name_is_in_output(self, formatter: JsonFormatter) -> None:
        record = self._make_exc_record("an error occurred", ValueError("boom"))
        output = json.loads(formatter.format(record))
        assert output.get("error_type") == "ValueError", f"Got: {output}"

    def test_student_email_not_in_output_for_exc(self, formatter: JsonFormatter) -> None:
        email = "<student_email>@example.invalid"
        record = self._make_exc_record("auth failure", RuntimeError(f"no account for {email}"))
        output = formatter.format(record)
        assert email not in output, f"Student email found in log output: {output!r}"

    def test_traceback_not_in_output(self, formatter: JsonFormatter) -> None:
        """Tracebacks are excluded — they can reveal code paths and PII values."""
        record = self._make_exc_record("failed", RuntimeError("boom"))
        output = formatter.format(record)
        assert "Traceback" not in output, f"Traceback found in log output: {output!r}"


# ---------------------------------------------------------------------------
# CorrelationIdFilter
# ---------------------------------------------------------------------------


class TestCorrelationIdFilter:
    @pytest.fixture()
    def filter_(self) -> CorrelationIdFilter:
        return CorrelationIdFilter()

    def _make_record(self) -> logging.LogRecord:
        return logging.LogRecord(
            name="app.test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="hello",
            args=(),
            exc_info=None,
        )

    def test_filter_returns_true(self, filter_: CorrelationIdFilter) -> None:
        record = self._make_record()
        assert filter_.filter(record) is True

    def test_correlation_id_injected_from_contextvar(self, filter_: CorrelationIdFilter) -> None:
        record = self._make_record()
        token = correlation_id_var.set("abc-123")
        try:
            filter_.filter(record)
        finally:
            correlation_id_var.reset(token)

        assert getattr(record, "correlation_id", None) == "abc-123", (
            f"Expected 'abc-123', got {getattr(record, 'correlation_id', None)!r}"
        )

    def test_empty_string_when_no_correlation_id_set(self, filter_: CorrelationIdFilter) -> None:
        """Outside a request context the correlation_id field is an empty string."""
        token = correlation_id_var.set("")
        try:
            record = self._make_record()
            filter_.filter(record)
        finally:
            correlation_id_var.reset(token)

        assert getattr(record, "correlation_id", None) == "", (
            f"Expected empty string, got {getattr(record, 'correlation_id', None)!r}"
        )

    def test_correlation_id_in_json_formatter_output(self) -> None:
        """End-to-end: CorrelationIdFilter + JsonFormatter produce correct JSON."""
        fmt = JsonFormatter()
        f = CorrelationIdFilter()

        record = self._make_record()
        token = correlation_id_var.set("req-xyz-789")
        try:
            f.filter(record)
            output = json.loads(fmt.format(record))
        finally:
            correlation_id_var.reset(token)

        assert output["correlation_id"] == "req-xyz-789", f"Got: {output}"


# ---------------------------------------------------------------------------
# _iso_timestamp helper
# ---------------------------------------------------------------------------


class TestIsoTimestamp:
    def test_format_ends_with_z(self) -> None:
        result = _iso_timestamp(1_700_000_000.123)
        assert result.endswith("Z"), f"Expected UTC 'Z' suffix: {result!r}"

    def test_format_contains_t_separator(self) -> None:
        result = _iso_timestamp(1_700_000_000.0)
        assert "T" in result, f"Expected ISO-8601 'T' separator: {result!r}"

    def test_milliseconds_included(self) -> None:
        # 1_700_000_000.5 = 1,700,000,000 seconds + 0.5 seconds = 500 milliseconds
        result = _iso_timestamp(1_700_000_000.5)
        # The 500ms component should appear in the output as ".500Z"
        assert ".500Z" in result, f"Expected '.500Z' in output: {result!r}"


# ---------------------------------------------------------------------------
# configure_logging smoke test
# ---------------------------------------------------------------------------


class TestConfigureLogging:
    def test_configure_logging_runs_without_error(self) -> None:
        configure_logging("INFO")  # should not raise

    def test_configure_logging_installs_json_formatter(self) -> None:
        configure_logging("INFO")
        root = logging.getLogger()
        assert root.handlers, "Expected at least one handler after configure_logging()"
        handler = root.handlers[0]
        assert isinstance(handler.formatter, JsonFormatter), (
            f"Expected JsonFormatter, got {type(handler.formatter)}"
        )

    def test_configure_logging_installs_correlation_id_filter(self) -> None:
        configure_logging("INFO")
        root = logging.getLogger()
        handler = root.handlers[0]
        filter_types = [type(f) for f in handler.filters]
        assert CorrelationIdFilter in filter_types, (
            f"CorrelationIdFilter not found. Filters: {filter_types}"
        )

    def test_configure_logging_is_idempotent(self) -> None:
        configure_logging("INFO")
        configure_logging("INFO")
        root = logging.getLogger()
        assert len(root.handlers) == 1, (
            f"Expected exactly 1 handler after two calls, got {len(root.handlers)}"
        )
