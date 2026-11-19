from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from app_base.core.settings import settings


class DecisionGateError(RuntimeError):
    pass


@dataclass(frozen=True)
class DecisionGateResult:
    route: str
    category: str
    confidence: float
    human_required: bool


class JevDecisionGate:
    """Classify support messages using Jev's typed Decisions API.

    Any provider, parsing, or confidence failure routes to a human. This keeps
    DiddiComms from using the support agent as a general-purpose chatbot.
    """

    def __init__(self, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.transport = transport

    async def classify(self, *, message: str, history: list[str] | None = None) -> DecisionGateResult:
        if not settings.openrouter_api_key:
            raise DecisionGateError("OPENROUTER_API_KEY is not configured")
        state = {"message": message, "history": (history or [])[-settings.decision_gate_history_messages :]}
        payload = {
            "model": settings.jev_model,
            "state": state,
            "questions": [
                {
                    "id": "route",
                    "type": "choice",
                    "options": ["support_allowed", "out_of_scope", "needs_human"],
                },
                {
                    "id": "category",
                    "type": "choice",
                    "options": [
                        "general",
                        "account",
                        "payment",
                        "ride",
                        "delivery",
                        "order",
                        "safety",
                        "technical",
                        "other",
                    ],
                },
                {"id": "human_required", "type": "boolean"},
            ],
        }
        try:
            async with httpx.AsyncClient(
                base_url=settings.openrouter_base_url.rstrip("/"),
                timeout=settings.jev_timeout_seconds,
                transport=self.transport,
            ) as client:
                response = await client.post(
                    "/../api/alpha/decisions",
                    json=payload,
                    headers={"Authorization": f"Bearer {settings.openrouter_api_key}"},
                )
                response.raise_for_status()
                data = response.json()
            result = self._parse(data)
            if result.confidence < settings.decision_gate_confidence_threshold or result.human_required:
                return DecisionGateResult("needs_human", result.category, result.confidence, True)
            return result
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
            raise DecisionGateError("Jev decision failed") from exc

    @staticmethod
    def _parse(data: dict[str, Any]) -> DecisionGateResult:
        answers = data["answers"]
        route = str(answers["route"]["value"])
        category = str(answers["category"]["value"])
        confidence = float(data.get("confidence", answers["route"].get("probability", 0)))
        human_required = bool(answers["human_required"]["value"])
        if route not in {"support_allowed", "out_of_scope", "needs_human"}:
            raise ValueError("invalid route")
        return DecisionGateResult(route, category, confidence, human_required)
