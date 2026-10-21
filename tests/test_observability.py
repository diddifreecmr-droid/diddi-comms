import json
import logging

import pytest

from app_base.core.metrics import increment, render_prometheus, reset_metrics, set_gauge
from app_base.core.observability import JsonRedactingFormatter, redact_text
from app_base.core.tracing import _trace_endpoint


def test_redaction_removes_tokens_phone_numbers_and_sensitive_values() -> None:
    text = 'Authorization=Bearer abc.def.ghi phone=+237600000001 body="private message" client_secret=secret'

    redacted = redact_text(text)

    assert "abc.def.ghi" not in redacted
    assert "+237600000001" not in redacted
    assert "private message" not in redacted
    assert "client_secret=secret" not in redacted


def test_json_formatter_keeps_only_safe_structured_context() -> None:
    record = logging.LogRecord(
        name="diddicomms.test",
        level=logging.WARNING,
        pathname=__file__,
        lineno=1,
        msg="failed Bearer token-value",
        args=(),
        exc_info=None,
    )
    record.request_id = "request-1"
    record.body = "must-not-appear"

    payload = json.loads(JsonRedactingFormatter().format(record))

    assert payload["request_id"] == "request-1"
    assert "token-value" not in payload["message"]
    assert "body" not in payload


def test_prometheus_renderer_distinguishes_counters_and_gauges() -> None:
    reset_metrics()
    increment("test_events_total", {"outcome": "ok"})
    set_gauge("test_queue_depth", 7)

    rendered = render_prometheus()

    assert "# TYPE test_events_total counter" in rendered
    assert 'test_events_total{outcome="ok"} 1' in rendered
    assert "# TYPE test_queue_depth gauge" in rendered
    assert "test_queue_depth 7" in rendered


def test_metric_name_cannot_change_type() -> None:
    reset_metrics()
    increment("test_collision")

    with pytest.raises(ValueError, match="already registered"):
        set_gauge("test_collision", 1)


def test_otlp_base_endpoint_gets_trace_path() -> None:
    assert _trace_endpoint("http://collector:4318") == "http://collector:4318/v1/traces"
    assert _trace_endpoint("http://collector:4318/v1/traces") == "http://collector:4318/v1/traces"
