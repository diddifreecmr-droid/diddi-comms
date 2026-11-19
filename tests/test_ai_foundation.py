from __future__ import annotations

import httpx
import pytest

from app_base.modules.ai.decision_gate import JevDecisionGate
from app_base.modules.ai.provider import OpenRouterClient


class JsonTransport(httpx.AsyncBaseTransport):
    def __init__(self, payload):
        self.payload = payload

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=self.payload, request=request)


@pytest.mark.asyncio
async def test_openrouter_returns_completion(monkeypatch) -> None:
    monkeypatch.setattr("app_base.modules.ai.provider.settings.openrouter_api_key", "test-key")
    monkeypatch.setattr("app_base.modules.ai.provider.settings.openrouter_primary_model", "test/model")
    client = OpenRouterClient(
        transport=JsonTransport({"model": "test/model", "choices": [{"message": {"content": "Hello"}}]})
    )

    result = await client.complete(messages=[{"role": "user", "content": "Hi"}])

    assert result.content == "Hello"
    assert result.used_fallback is False


def test_jev_parser_reads_typed_answers() -> None:
    result = JevDecisionGate._parse(
        {
            "confidence": 0.95,
            "answers": {
                "route": {"value": "support_allowed"},
                "category": {"value": "payment"},
                "human_required": {"value": False},
            },
        }
    )

    assert result.route == "support_allowed"
    assert result.category == "payment"
    assert result.confidence == 0.95
