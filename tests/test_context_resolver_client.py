from __future__ import annotations

from uuid import UUID

import httpx
import pytest

from app_base.modules.context.infra.resolver_client import ContextResolverClient, OwnerServiceConfig


class FakeTokenClient:
    client_id = "diddicomms-local-diddigo"

    def __init__(self) -> None:
        self.scopes: list[str] = []

    async def access_token(self, scope: str) -> str:
        self.scopes.append(scope)
        return "service-token"


@pytest.mark.asyncio
async def test_context_resolver_uses_owner_contract() -> None:
    token_client = FakeTokenClient()
    seen_request: httpx.Request | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal seen_request
        seen_request = request
        return httpx.Response(
            200,
            json={
                "task": {
                    "owner_service": "diddigo",
                    "task_type": "ride",
                    "task_id": "11111111-1111-1111-1111-111111111111",
                },
                "state": "driver_assigned",
                "version": 12,
                "participants": [
                    {
                        "user_id": "22222222-2222-2222-2222-222222222222",
                        "role": "passenger",
                        "phone_e164": "+237600000001",
                    },
                    {
                        "user_id": "33333333-3333-3333-3333-333333333333",
                        "role": "driver",
                        "phone_e164": "+237600000002",
                    },
                ],
                "messaging_allowed": True,
                "calling_allowed": True,
                "closes_at": None,
            },
        )

    resolver = ContextResolverClient(
        OwnerServiceConfig(
            name="diddigo",
            base_url="https://go.test",
            context_scope="diddigo:comms-task:read",
            service_token_client=token_client,  # type: ignore[arg-type]
        ),
        transport=httpx.MockTransport(handler),
    )

    context = await resolver.get_task("ride", UUID("11111111-1111-1111-1111-111111111111"))

    assert token_client.scopes == ["diddigo:comms-task:read"]
    assert seen_request is not None
    assert seen_request.url.path == "/internal/v1/comms/tasks/ride/11111111-1111-1111-1111-111111111111"
    assert seen_request.headers["Authorization"] == "Bearer service-token"
    assert seen_request.headers["X-Client-ID"] == "diddicomms-local-diddigo"
    assert context.task.owner_service == "diddigo"
    assert context.task.task_type == "ride"
    assert context.messaging_allowed is True
    assert context.participant_user_ids() == {
        UUID("22222222-2222-2222-2222-222222222222"),
        UUID("33333333-3333-3333-3333-333333333333"),
    }
