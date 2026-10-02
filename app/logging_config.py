import contextvars
import json
import logging
import sys
from datetime import datetime, timezone

request_id_ctx: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "request_id", default=None
)


class JSONFormatter(logging.Formatter):
    """Standard library logging formatter outputting JSON lines."""

    def format(self, record: logging.LogRecord) -> str:
        log_payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Automatically include active request_id from contextvar if available
        req_id = request_id_ctx.get()
        if req_id:
            log_payload["request_id"] = req_id

        # Automatically correlate with active OpenTelemetry trace context if available
        try:
            from opentelemetry import trace
            span = trace.get_current_span()
            if span and span.get_span_context().is_valid:
                ctx = span.get_span_context()
                log_payload["trace_id"] = format(ctx.trace_id, "032x")
                log_payload["span_id"] = format(ctx.span_id, "016x")
        except Exception:
            pass

        # Include standard exception information if present
        if record.exc_info:
            log_payload["exception"] = self.formatException(record.exc_info)

        # Include custom extra fields if passed in record.__dict__
        standard_attrs = {
            "name", "msg", "args", "levelname", "levelno", "pathname",
            "filename", "module", "exc_info", "exc_text", "stack_info",
            "lineno", "funcName", "created", "msecs", "relativeCreated",
            "thread", "threadName", "processName", "process", "message",
        }
        extras = {
            k: v for k, v in record.__dict__.items() if k not in standard_attrs
        }
        if extras:
            log_payload["extra"] = extras

        return json.dumps(log_payload)


def setup_logging(log_level: str = "INFO") -> None:
    """Configure root logger with JSON formatting on stdout."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))
