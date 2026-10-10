from __future__ import annotations

import re
import threading
from collections import defaultdict
from collections.abc import Mapping
from typing import Any

_UUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
_STORE: dict[tuple[str, tuple[tuple[str, str], ...]], float] = defaultdict(float)
_LOCK = threading.Lock()

_HELP = {
    "diddicomms_http_requests_total": "Total HTTP requests handled by DiddiComms.",
    "diddicomms_http_request_duration_ms_count": "Total observed HTTP request durations.",
    "diddicomms_http_request_duration_ms_sum": "Sum of observed HTTP request durations in milliseconds.",
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
        _STORE[key] += float(amount)


def render_prometheus() -> str:
    with _LOCK:
        items = sorted(_STORE.items())
    lines: list[str] = []
    emitted_headers: set[str] = set()
    for (name, labels), value in items:
        if name not in emitted_headers:
            lines.append(f"# HELP {name} {_HELP.get(name, name)}")
            lines.append(f"# TYPE {name} counter")
            emitted_headers.add(name)
        lines.append(f"{name}{_format_labels(labels)} {_format_number(value)}")
    return "\n".join(lines) + ("\n" if lines else "")


def reset_metrics() -> None:
    with _LOCK:
        _STORE.clear()


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

