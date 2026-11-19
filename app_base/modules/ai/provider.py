from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from app_base.core.settings import settings


class AIProviderError(RuntimeError):
    pass


@dataclass(frozen=True)
class AICompletion:
    content: str
    model: str
    used_fallback: bool
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


class OpenRouterClient:
    def __init__(self, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.transport = transport

    async def complete(self, *, messages: list[dict[str, Any]], max_tokens: int = 500) -> AICompletion:
        if not settings.openrouter_api_key:
            raise AIProviderError("OPENROUTER_API_KEY is not configured")

        last_error: Exception | None = None
        for index, model in enumerate((settings.openrouter_primary_model, settings.openrouter_fallback_model)):
            try:
                return await self._complete_model(
                    model=model,
                    messages=messages,
                    max_tokens=max_tokens,
                    used_fallback=index > 0,
                )
            except (AIProviderError, httpx.HTTPError) as exc:
                last_error = exc
        raise AIProviderError("OpenRouter primary and fallback models failed") from last_error

    async def _complete_model(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        max_tokens: int,
        used_fallback: bool,
    ) -> AICompletion:
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "reasoning": {"effort": settings.openrouter_reasoning_effort},
        }
        headers = {"Authorization": f"Bearer {settings.openrouter_api_key}"}
        async with httpx.AsyncClient(
            base_url=settings.openrouter_base_url.rstrip("/"),
            timeout=30.0,
            transport=self.transport,
        ) as client:
            response = await client.post("/chat/completions", json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()

        try:
            choice = data["choices"][0]
            content = choice.get("message", {}).get("content")
            usage = data.get("usage") or {}
            if not isinstance(content, str) or not content.strip():
                raise ValueError("empty completion")
            return AICompletion(
                content=content.strip(),
                model=str(data.get("model") or model),
                used_fallback=used_fallback,
                prompt_tokens=usage.get("prompt_tokens"),
                completion_tokens=usage.get("completion_tokens"),
            )
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise AIProviderError(f"Invalid completion from model {model}") from exc
