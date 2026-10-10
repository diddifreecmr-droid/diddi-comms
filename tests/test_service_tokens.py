from __future__ import annotations

import httpx
import pytest

from app_base.core.service_tokens import ServiceTokenClient


@pytest.mark.asyncio
async def test_service_token_client_uses_client_credentials_contract() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        body = (await request.aread()).decode()
        assert request.headers["X-Client-ID"] == "diddicomms-local-diddigo"
        assert "grant_type=client_credentials" in body
        assert "client_id=diddicomms-local-diddigo" in body
        assert "audience=diddigo" in body
        assert "scope=diddigo%3Acomms-task%3Aread" in body
        return httpx.Response(200, json={"access_token": "service-token", "expires_in": 600})

    client = ServiceTokenClient(
        token_url="https://identity.test/identity/v1/auth/service/token",
        client_id="diddicomms-local-diddigo",
        client_secret="secret",
        audience="diddigo",
        transport=httpx.MockTransport(handler),
    )

    token = await client.access_token("diddigo:comms-task:read")
    cached = await client.access_token("diddigo:comms-task:read")

    assert token == "service-token"
    assert cached == "service-token"
    assert len(requests) == 1
