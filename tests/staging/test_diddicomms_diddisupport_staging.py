from __future__ import annotations

import os
from uuid import uuid4

import httpx
import pytest

COMMS_BASE_URL = os.getenv(
    "DIDDICOMMS_STAGING_BASE_URL",
    "https://diddi-comm-staging.diddifree.com",
).rstrip("/")
SUPPORT_BASE_URL = os.getenv(
    "DIDDISUPPORT_STAGING_BASE_URL",
    "http://support-backend-staging.diddifree.com",
).rstrip("/")
TIMEOUT_SECONDS = float(os.getenv("STAGING_HTTP_TIMEOUT_SECONDS", "15"))

pytestmark = [
    pytest.mark.integration,
    pytest.mark.staging,
    pytest.mark.skipif(
        os.getenv("RUN_STAGING_SMOKE_TESTS") != "1",
        reason="set RUN_STAGING_SMOKE_TESTS=1 to call the deployed staging services",
    ),
]


def _get_json(base_url: str, path: str) -> dict:
    for attempt in range(2):
        try:
            with httpx.Client(timeout=TIMEOUT_SECONDS, follow_redirects=True) as client:
                response = client.get(f"{base_url}{path}", headers={"Connection": "close"})
            response.raise_for_status()
            payload = response.json()
            assert isinstance(payload, dict)
            return payload
        except httpx.TransportError:
            if attempt == 1:
                raise
    raise AssertionError("unreachable")


def _assert_operations(openapi: dict, expected: dict[str, set[str]]) -> None:
    paths = openapi.get("paths")
    assert isinstance(paths, dict), "OpenAPI document has no paths object"
    missing = [
        f"{method.upper()} {path}"
        for path, methods in expected.items()
        for method in methods
        if method not in paths.get(path, {})
    ]
    assert not missing, f"staging contract is missing: {', '.join(missing)}"


def test_staging_services_are_live_and_ready() -> None:
    comms_health = _get_json(COMMS_BASE_URL, "/health")
    comms_ready = _get_json(COMMS_BASE_URL, "/ready")
    support_live = _get_json(SUPPORT_BASE_URL, "/health/live")
    support_ready = _get_json(SUPPORT_BASE_URL, "/health/ready")
    support_ping = _get_json(SUPPORT_BASE_URL, "/support/v1/ping")

    assert comms_health.get("status") == "ok"
    assert comms_ready.get("status") == "ready"
    assert support_live.get("status") in {"ok", "alive"}
    assert support_ready.get("status") in {"ok", "ready"}
    assert support_ping.get("status") in {"ok", "pong"}


def test_diddicomms_staging_openapi_exposes_frontend_support_contract() -> None:
    comms_openapi = _get_json(COMMS_BASE_URL, "/openapi.json")

    _assert_operations(
        comms_openapi,
        {
            "/comms/v1/support/conversations": {"get", "post"},
            "/comms/v1/support/categories": {"get"},
            "/comms/v1/conversations/{conversation_id}/messages": {"get", "post"},
        },
    )


def test_diddisupport_staging_openapi_exposes_internal_comms_contract() -> None:
    support_openapi = _get_json(SUPPORT_BASE_URL, "/openapi.json")

    _assert_operations(
        support_openapi,
        {
            "/support/v1/internal/cases": {"post"},
            "/support/v1/internal/cases/{case_id}/context": {"get"},
            "/support/v1/internal/cases/{case_id}/messages": {"get", "post"},
            "/support/v1/internal/context/{origin_service}/{resource_type}/{resource_id}": {"get"},
        },
    )


def test_staging_user_can_open_and_continue_general_support_conversation() -> None:
    if os.getenv("RUN_STAGING_WRITE_TESTS") != "1":
        pytest.skip("set RUN_STAGING_WRITE_TESTS=1 to create a real staging Support case")
    token = os.getenv("DIDDICOMMS_STAGING_USER_TOKEN")
    if not token:
        pytest.skip("DIDDICOMMS_STAGING_USER_TOKEN is required for the write journey")

    run_id = uuid4()
    headers = {
        "Authorization": f"Bearer {token}",
        "Idempotency-Key": f"staging-support-{run_id}",
        "X-Request-ID": str(run_id),
    }
    with httpx.Client(timeout=TIMEOUT_SECONDS, follow_redirects=True) as client:
        opened = client.post(
            f"{COMMS_BASE_URL}/comms/v1/support/conversations",
            headers=headers,
            json={
                "category": "general",
                "subject": "Automated staging contract check",
                "message": f"Initial staging test message {run_id}",
                "priority": "normal",
            },
        )
        opened.raise_for_status()
        conversation = opened.json()
        conversation_id = conversation["conversation_id"]
        assert conversation["support_case_id"]

        continued = client.post(
            f"{COMMS_BASE_URL}/comms/v1/conversations/{conversation_id}/messages",
            headers={
                **headers,
                "Idempotency-Key": f"staging-support-message-{run_id}",
            },
            json={
                "client_message_id": f"staging-{run_id}",
                "body": f"Follow-up staging test message {run_id}",
            },
        )
        continued.raise_for_status()
        assert continued.json()["conversation_id"] == conversation_id

        history = client.get(
            f"{COMMS_BASE_URL}/comms/v1/conversations/{conversation_id}/messages",
            headers={"Authorization": f"Bearer {token}"},
        )
        history.raise_for_status()
        messages = history.json()

    assert any(item.get("body") == f"Follow-up staging test message {run_id}" for item in messages)
    assert all(item.get("visibility", "user_visible") == "user_visible" for item in messages)
