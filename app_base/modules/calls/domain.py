from __future__ import annotations

from enum import StrEnum


class CallClientResult(StrEnum):
    STARTED = "started"
    CANCELLED = "cancelled"
    FAILED = "failed"
    UNKNOWN = "unknown"
