from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

from app_base.modules.events.consumer import InboundEvent

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = PROJECT_ROOT / "docs" / "diddiconnect" / "fixtures" / "support-event-envelope.v1.json"


def test_consumer_parses_versioned_diddisupport_event_fixture() -> None:
    envelope = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    parsed = InboundEvent.from_stream_fields({"event": json.dumps(envelope, separators=(",", ":"))})

    assert parsed.event_id == UUID("cccccccc-3333-3333-3333-cccccccccccc")
    assert parsed.event_type == "support.case.message.created.v1"
    assert parsed.aggregate_id == "aaaaaaaa-1111-1111-1111-aaaaaaaaaaaa"
    assert parsed.aggregate_version == 3
    assert parsed.payload["visibility"] == "user_visible"
    assert "body" not in parsed.payload


def test_test_suite_does_not_import_sibling_repositories() -> None:
    forbidden_markers = (
        "DIDDISUPPORT_" + "REPO_PATH",
        "sys.path." + "insert",
        "sys.path." + "append",
    )
    violations = []
    for path in (PROJECT_ROOT / "tests").rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        if any(marker in source for marker in forbidden_markers):
            violations.append(str(path.relative_to(PROJECT_ROOT)))

    assert violations == [], f"Tests must use local contracts, not sibling repositories: {violations}"
