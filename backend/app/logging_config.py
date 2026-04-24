"""Structured JSON logging for the Rubric Grading Engine.

Provides:
- ``correlation_id_var`` — ContextVar for the per-request correlation ID.
- ``CorrelationIdFilter`` — injects ``correlation_id`` into every LogRecord.
- ``JsonFormatter`` — serialises LogRecords as single-line JSON.
- ``configure_logging()`` — call once at startup to activate JSON logging.

Usage in application startup::

    from app.logging_config import configure_logging
    configure_logging(settings.log_level)

Usage in middleware to set the per-request ID::

    from app.logging_config import correlation_id_var

    token = correlation_id_var.set(request_id)
    try:
        response = await call_next(request)
    finally:
        correlation_id_var.reset(token)

Security notes
--------------
- ``JsonFormatter`` never includes exception messages or tracebacks in the
  JSON payload — only the exception *type* name is emitted.  Exception
  messages can contain student PII from upstream callers (database error
  messages, LLM response fragments, etc.).
- Callers are responsible for never passing student names, essay text, or
  other FERPA-protected values via ``extra=``.  Only entity IDs should appear
  in log lines.
"""

from __future__ import annotations

import json
import logging
import time
from contextvars import ContextVar

# Per-request correlation ID.  Set by CorrelationIdMiddleware for every
# FastAPI request and by the Celery task_prerun signal in worker processes.
# Defaults to an empty string so log lines outside a request context are
# still valid JSON (no missing key).
correlation_id_var: ContextVar[str] = ContextVar("correlation_id", default="")


class CorrelationIdFilter(logging.Filter):
    """Inject ``correlation_id`` into every LogRecord from the ContextVar.

    Attach this filter to every handler that should carry the per-request ID::

        handler.addFilter(CorrelationIdFilter())
    """

    def filter(self, record: logging.LogRecord) -> bool:
        # LogRecord does not declare correlation_id; we add it as a dynamic
        # attribute so that JsonFormatter can include it without needing to call
        # correlation_id_var.get() inside the formatter itself.
        record.correlation_id = correlation_id_var.get("")
        return True


class JsonFormatter(logging.Formatter):
    """Emit each log record as a single-line JSON object.

    Fixed fields in every line:

    - ``timestamp``      — ISO-8601 UTC with millisecond precision.
    - ``level``          — Python level name (INFO, WARNING, ERROR, …).
    - ``logger``         — Dotted logger name (e.g. ``app.services.grading``).
    - ``service``        — Static string ``"rubric-grading-engine"``.
    - ``correlation_id`` — Per-request UUID set by CorrelationIdMiddleware;
                           empty string for background tasks without a request.
    - ``message``        — Formatted log message.

    Additional fields from ``extra=`` keyword arguments are merged into the
    object.  Standard LogRecord internal attributes are excluded so that only
    app-defined structured fields appear alongside the fixed set above.

    Security: exception messages and tracebacks are **never** included.  Only
    ``error_type`` (the exception class name) is added when an exception is
    present.  This prevents student PII from leaking into log aggregation
    services via exception messages that may contain database query values or
    LLM response content.
    """

    _SERVICE = "rubric-grading-engine"

    # Standard LogRecord attributes that must not be copied into the JSON
    # payload as extra fields.  Keeps the output compact and avoids
    # double-encoding already-present fixed fields.
    _SKIP: frozenset[str] = frozenset(
        {
            "args",
            "created",
            "exc_info",
            "exc_text",
            "filename",
            "funcName",
            "levelname",
            "levelno",
            "lineno",
            "message",
            "module",
            "msecs",
            "msg",
            "name",
            "pathname",
            "process",
            "processName",
            "relativeCreated",
            "stack_info",
            "taskName",
            "thread",
            "threadName",
            # Added by CorrelationIdFilter — already present in fixed fields.
            "correlation_id",
        }
    )

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": _iso_timestamp(record.created),
            "level": record.levelname,
            "logger": record.name,
            "service": self._SERVICE,
            "correlation_id": getattr(record, "correlation_id", ""),
            "message": record.getMessage(),
        }

        # Merge structured extra fields (entity IDs, error_type, etc.).
        for key, val in record.__dict__.items():
            if key not in self._SKIP:
                payload[key] = val

        # Include exception *type* only — never the message or traceback.
        # Exception messages can contain student PII from upstream callers.
        if record.exc_info and record.exc_info[0] is not None:
            payload["error_type"] = record.exc_info[0].__name__

        return json.dumps(payload, default=str)


def _iso_timestamp(created: float) -> str:
    """Convert a Unix epoch float to ISO-8601 UTC with millisecond precision.

    Example output: ``"2025-01-15T14:32:01.123Z"``
    """
    millis = int(created * 1000)
    secs, ms = divmod(millis, 1000)
    t = time.gmtime(secs)
    return (
        f"{t.tm_year:04d}-{t.tm_mon:02d}-{t.tm_mday:02d}T"
        f"{t.tm_hour:02d}:{t.tm_min:02d}:{t.tm_sec:02d}.{ms:03d}Z"
    )


def configure_logging(level: str = "INFO") -> None:
    """Configure the root logger to emit structured JSON to stdout.

    Idempotent — existing handlers are replaced on each call to prevent
    duplicate output (e.g. when ``create_app()`` is called multiple times in
    tests).

    Args:
        level: Logging level string accepted by ``logging.getLevelName``
               (e.g. ``"DEBUG"``, ``"INFO"``, ``"WARNING"``).
    """
    import sys  # noqa: PLC0415

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(CorrelationIdFilter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
