from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest

from app_base.modules.events.consumer import InboundEvent

SUPPORT_REPO = Path(
    os.getenv(
        "DIDDISUPPORT_REPO_PATH",
        str(Path(__file__).resolve().parents[3] / "diddi-support"),
    )
)

pytestmark = pytest.mark.skipif(
    not (SUPPORT_REPO / "src" / "diddi_support" / "infrastructure" / "outbox.py").exists(),
    reason="requires a DiddiSupport checkout or DIDDISUPPORT_REPO_PATH",
)


def test_consumer_parses_the_real_diddisupport_event_envelope() -> None:
    sys.path.insert(0, str(SUPPORT_REPO / "src"))
    try:
        from diddi_support.infrastructure.outbox import OutboxRecord, event_envelope

        event_id = UUID("cccccccc-3333-3333-3333-cccccccccccc")
        case_id = UUID("aaaaaaaa-1111-1111-1111-aaaaaaaaaaaa")
        record = OutboxRecord(
            id=event_id,
            event_type="support.case.message.created",
            aggregate_id=str(case_id),
            aggregate_version=3,
            occurred_at=datetime(2026, 10, 21, tzinfo=UTC),
            attempts=1,
            payload={
                "case_id": str(case_id),
                "message_id": "dddddddd-4444-4444-4444-dddddddddddd",
                "visibility": "user_visible",
                "body": "must be removed by the provider envelope",
            },
        )

        fields = {"event": json.dumps(event_envelope(record), separators=(",", ":"))}
        parsed = InboundEvent.from_stream_fields(fields)

        assert parsed.event_id == event_id
        assert parsed.event_type == "support.case.message.created.v1"
        assert parsed.aggregate_id == str(case_id)
        assert parsed.aggregate_version == 3
        assert parsed.payload["visibility"] == "user_visible"
        assert "body" not in parsed.payload
    finally:
        sys.path.remove(str(SUPPORT_REPO / "src"))
