from uuid import UUID

import httpx
import pytest

from app_base.core.errors import ApiError
from app_base.modules.support.read_client import DiddiSupportReadClient, DiddiSupportReadConfig


class FakeTokenClient:
    client_id = "diddicomms-local-diddicomms"

    def __init__(self) -> None:
        self.scopes: list[str] = []

    async def access_token(self, scope: str) -> str:
        self.scopes.append(scope)
        return "support-service-token"


def make_client(handler):
    token_client = FakeTokenClient()
    client = DiddiSupportReadClient(
        DiddiSupportReadConfig(
            base_url="https://support.test",
            client_id=token_client.client_id,
            scope="diddi-support:cases:read",
            service_token_client=token_client,  # type: ignore[arg-type]
        ),
        transport=httpx.MockTransport(handler),
    )
    return client, token_client


@pytest.mark.asyncio
async def test_reads_context_with_support_contract_headers_and_path() -> None:
    seen: httpx.Request | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal seen
        seen = request
        return httpx.Response(
            200,
            json={
                "protocol": "diddi.context.v1",
                "origin_service": "diddisend",
                "resource_type": "delivery",
                "resource_id": "delivery-123",
                "data": {"status": "in_transit"},
                "redacted_fields": [],
                "as_of": "2026-10-20T12:00:00Z",
                "fetched_at": "2026-10-20T12:00:01Z",
            },
        )

    client, token_client = make_client(handler)
    result = await client.get_context("diddisend", "delivery", "delivery-123")

    assert token_client.scopes == ["diddi-support:cases:read"]
    assert seen is not None
    assert seen.url.path == "/support/v1/internal/context/diddisend/delivery/delivery-123"
    assert seen.headers["Authorization"] == "Bearer support-service-token"
    assert seen.headers["X-Client-ID"] == "diddicomms-local-diddicomms"
    assert seen.headers["X-Request-ID"]
    assert result.protocol == "diddi.context.v1"
    assert result.data == {"status": "in_transit"}


@pytest.mark.asyncio
async def test_reads_case_context() -> None:
    client, _ = make_client(
        lambda request: httpx.Response(
            200,
            json={
                "case": {"case_id": "case-1", "status": "open"},
                "context": {
                    "protocol": "diddi.context.v1",
                    "origin_service": "diddigo",
                    "resource_type": "ride",
                    "resource_id": "ride-1",
                    "data": {},
                    "redacted_fields": [],
                    "as_of": "2026-10-20T12:00:00Z",
                    "fetched_at": "2026-10-20T12:00:01Z",
                },
            },
        )
    )

    result = await client.get_case_context(UUID("11111111-1111-1111-1111-111111111111"))
    assert result.case["case_id"] == "case-1"
    assert result.context is not None
    assert result.context.resource_type == "ride"


@pytest.mark.asyncio
async def test_maps_support_errors() -> None:
    client, _ = make_client(lambda request: httpx.Response(503))

    with pytest.raises(ApiError) as exc:
        await client.get_context("diddifood", "order", "order-1")

    assert exc.value.status_code == 503
    assert exc.value.code == "DIDDISUPPORT_UNAVAILABLE"
