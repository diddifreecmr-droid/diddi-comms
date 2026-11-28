from __future__ import annotations

import httpx
import pytest

from app_base.modules.ai.decision_gate import JevDecisionGate
from app_base.modules.ai.provider import OpenRouterClient
from app_base.modules.conversations.presentation.router import _remote_sender_role, _remote_sender_type


class JsonTransport(httpx.AsyncBaseTransport):
    def __init__(self, payload):
        self.payload = payload

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=self.payload, request=request)


class RecordingDecisionTransport(httpx.AsyncBaseTransport):
    def __init__(self) -> None:
        self.url: httpx.URL | None = None

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.url = request.url
        return httpx.Response(
            200,
            json={
                "confidence": 0.95,
                "answers": {
                    "route": {"value": "support_allowed"},
                    "category": {"value": "general"},
                    "human_required": {"value": False},
                },
            },
            request=request,
        )


class FallbackTransport(httpx.AsyncBaseTransport):
    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/chat/completions") and request.content:
            if b"primary/model" in request.content:
                return httpx.Response(500, request=request)
            return httpx.Response(
                200,
                json={"model": "fallback/model", "choices": [{"message": {"content": "Fallback"}}]},
                request=request,
            )
        return httpx.Response(500, request=request)


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


@pytest.mark.asyncio
async def test_openrouter_uses_fallback_model(monkeypatch) -> None:
    monkeypatch.setattr("app_base.modules.ai.provider.settings.openrouter_api_key", "test-key")
    monkeypatch.setattr("app_base.modules.ai.provider.settings.openrouter_primary_model", "primary/model")
    monkeypatch.setattr("app_base.modules.ai.provider.settings.openrouter_fallback_model", "fallback/model")

    result = await OpenRouterClient(transport=FallbackTransport()).complete(
        messages=[{"role": "user", "content": "Hi"}]
    )

    assert result.content == "Fallback"
    assert result.used_fallback is True


@pytest.mark.asyncio
async def test_jev_uses_openrouter_alpha_decisions_path(monkeypatch) -> None:
    monkeypatch.setattr("app_base.modules.ai.decision_gate.settings.openrouter_api_key", "test-key")
    monkeypatch.setattr(
        "app_base.modules.ai.decision_gate.settings.openrouter_base_url",
        "https://openrouter.ai/api/v1",
    )
    transport = RecordingDecisionTransport()

    result = await JevDecisionGate(transport=transport).classify(message="I need help")

    assert result.route == "support_allowed"
    assert transport.url is not None
    assert str(transport.url) == "https://openrouter.ai/api/alpha/decisions"


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


def test_support_sender_attribution_includes_ai_and_admin() -> None:
    assert _remote_sender_type("ai") == "ai"
    assert _remote_sender_role("assistant") == "ai"
    assert _remote_sender_type("backoffice_operator") == "admin"
    assert _remote_sender_role("admin") == "admin"
