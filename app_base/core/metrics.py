from __future__ import annotations

import json
import re
import threading
from collections import defaultdict
from collections.abc import Mapping
from typing import Any

_UUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
_STORE: dict[tuple[str, tuple[tuple[str, str], ...]], float] = defaultdict(float)
_TYPES: dict[str, str] = {}
_LOCK = threading.Lock()

_HELP = {
    "diddicomms_http_requests_total": "Total HTTP requests handled by DiddiComms.",
    "diddicomms_http_request_duration_ms_count": "Total observed HTTP request durations.",
    "diddicomms_http_request_duration_ms_sum": "Sum of observed HTTP request durations in milliseconds.",
    "diddicomms_delivery_receipts_total": "Message delivery receipt transitions.",
    "diddicomms_inbound_events_total": "Inbound events by processing outcome.",
    "diddicomms_websocket_connections_total": "WebSocket connection outcomes.",
    "diddicomms_websocket_active_connections": "Current WebSocket connections held by this process.",
    "diddicomms_rate_limit_denials_total": "Rate-limit denials by operation and dimension.",
    "diddicomms_auth_denials_total": "Authentication and authorization denials by error code.",
    "diddicomms_outbox_events_total": "Outbox publication outcomes.",
    "diddicomms_outbox_pending_events": "Current unpublished outbox events eligible for retry.",
    "diddicomms_outbox_oldest_event_age_seconds": "Age of the oldest unpublished outbox event.",
    "diddicomms_inbound_pending_events": "Current pending inbound stream entries for this consumer group.",
    "diddicomms_inbound_consumer_lag": "Current Redis-reported lag for the inbound consumer group.",
    "diddicomms_worker_consecutive_failures": "Current consecutive worker loop failures.",
    "diddicomms_worker_last_success_unixtime": "Unix timestamp of the worker's last successful loop.",
}


def record_http_request(*, method: str, path: str, status_code: int, duration_ms: float) -> None:
    labels = {
        "method": method.upper(),
        "path": normalize_path(path),
        "status_code": str(status_code),
        "status_family": f"{status_code // 100}xx",
    }
    increment("diddicomms_http_requests_total", labels)
    duration_labels = {"method": method.upper(), "path": normalize_path(path)}
    increment("diddicomms_http_request_duration_ms_count", duration_labels)
    increment("diddicomms_http_request_duration_ms_sum", duration_labels, duration_ms)


def increment(name: str, labels: Mapping[str, Any] | None = None, amount: float = 1.0) -> None:
    key = (name, _labels_tuple(labels or {}))
    with _LOCK:
        _register_type(name, "counter")
        _STORE[key] += float(amount)


def set_gauge(name: str, value: float, labels: Mapping[str, Any] | None = None) -> None:
    key = (name, _labels_tuple(labels or {}))
    with _LOCK:
        _register_type(name, "gauge")
        _STORE[key] = float(value)


async def shared_increment(
    redis: Any,
    redis_key: str,
    name: str,
    labels: Mapping[str, Any] | None = None,
    amount: float = 1.0,
) -> None:
    await redis.hincrbyfloat(redis_key, _shared_sample_key("counter", name, labels or {}), float(amount))


async def shared_set_gauge(
    redis: Any,
    redis_key: str,
    name: str,
    value: float,
    labels: Mapping[str, Any] | None = None,
) -> None:
    await redis.hset(redis_key, _shared_sample_key("gauge", name, labels or {}), float(value))


async def render_shared_metrics(redis: Any, redis_key: str) -> str:
    try:
        raw_samples = await redis.hgetall(redis_key)
    except Exception:
        return ""
    samples: list[tuple[str, str, tuple[tuple[str, str], ...], float]] = []
    for raw_key, raw_value in raw_samples.items():
        try:
            metric_type, name, labels = json.loads(raw_key)
            samples.append((str(name), str(metric_type), tuple(tuple(item) for item in labels), float(raw_value)))
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
    lines: list[str] = []
    emitted_headers: set[str] = set()
    for name, metric_type, labels, value in sorted(samples):
        if name not in emitted_headers:
            lines.append(f"# HELP {name} {_HELP.get(name, name)}")
            lines.append(f"# TYPE {name} {metric_type}")
            emitted_headers.add(name)
        lines.append(f"{name}{_format_labels(labels)} {_format_number(value)}")
    return "\n".join(lines) + ("\n" if lines else "")


def render_prometheus() -> str:
    with _LOCK:
        items = sorted(_STORE.items())
    lines: list[str] = []
    emitted_headers: set[str] = set()
    for (name, labels), value in items:
        if name not in emitted_headers:
            lines.append(f"# HELP {name} {_HELP.get(name, name)}")
            lines.append(f"# TYPE {name} {_TYPES.get(name, 'gauge')}")
            emitted_headers.add(name)
        lines.append(f"{name}{_format_labels(labels)} {_format_number(value)}")
    return "\n".join(lines) + ("\n" if lines else "")


def reset_metrics() -> None:
    with _LOCK:
        _STORE.clear()
        _TYPES.clear()


def _register_type(name: str, metric_type: str) -> None:
    existing = _TYPES.get(name)
    if existing is not None and existing != metric_type:
        raise ValueError(f"metric {name} already registered as {existing}")
    _TYPES[name] = metric_type


def _shared_sample_key(metric_type: str, name: str, labels: Mapping[str, Any]) -> str:
    return json.dumps([metric_type, name, _labels_tuple(labels)], separators=(",", ":"))


def normalize_path(path: str) -> str:
    return _UUID_RE.sub(":uuid", path)


def _labels_tuple(labels: Mapping[str, Any]) -> tuple[tuple[str, str], ...]:
    return tuple(sorted((str(key), _clean_label_value(value)) for key, value in labels.items()))


def _clean_label_value(value: Any) -> str:
    cleaned = str(value)
    if _UUID_RE.fullmatch(cleaned):
        return ":uuid"
    return cleaned[:120]


def _format_labels(labels: tuple[tuple[str, str], ...]) -> str:
    if not labels:
        return ""
    return "{" + ",".join(f'{key}="{_escape_label(value)}"' for key, value in labels) + "}"


def _escape_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def _format_number(value: float) -> str:
    return str(int(value)) if value.is_integer() else f"{value:.6f}".rstrip("0").rstrip(".")
