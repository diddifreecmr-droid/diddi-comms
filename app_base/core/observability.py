from __future__ import annotations

import json
import logging
import re
import sys
from datetime import UTC, datetime

_BEARER_TOKEN = re.compile(r"(?i)bearer\s+[a-z0-9._~+/-]+=*")
_PHONE_NUMBER = re.compile(r"(?<!\w)\+[1-9][0-9]{7,14}(?!\w)")
_SENSITIVE_VALUE = re.compile(
    r'(?i)("?(?:password|client_secret|access_token|refresh_token|body)"?\s*[:=]\s*)' r'("[^"\s]*"|[^,\s}]+)'
)


def redact_text(value: str) -> str:
    value = _BEARER_TOKEN.sub("Bearer [REDACTED]", value)
    value = _PHONE_NUMBER.sub("[REDACTED_PHONE]", value)
    return _SENSITIVE_VALUE.sub(r"\1[REDACTED]", value)


class JsonRedactingFormatter(logging.Formatter):
    safe_extra_fields = ("request_id", "event_id", "event_type", "stream_id", "failure_type")

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "message": redact_text(record.getMessage()),
        }
        for field in self.safe_extra_fields:
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = redact_text(str(value))
        try:
            from opentelemetry import trace

            context = trace.get_current_span().get_span_context()
            if context.is_valid:
                payload["trace_id"] = format(context.trace_id, "032x")
                payload["span_id"] = format(context.span_id, "016x")
        except ImportError:
            pass
        if record.exc_info:
            payload["exception_type"] = record.exc_info[0].__name__
        return json.dumps(payload, separators=(",", ":"), sort_keys=True)


def configure_logging(level: str) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonRedactingFormatter())
    logging.basicConfig(level=getattr(logging, level.upper(), logging.INFO), handlers=[handler], force=True)
