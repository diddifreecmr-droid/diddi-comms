from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx

from app_base.core.settings import settings

logger = logging.getLogger(__name__)


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
            logger.error("ai_decision_unavailable", extra={"reason": "openrouter_api_key_missing"})
            raise DecisionGateError("OPENROUTER_API_KEY is not configured")
        state = {"message": message, "history": (history or [])[-settings.decision_gate_history_messages :]}
        payload = {
            "model": settings.jev_model,
            "state": state,
            "questions": {
                "route": {
                    "type": "choice",
                    "instructions": "Which support route should handle this message?",
                    "criteria": {
                        "support_allowed": "The message is a genuine DiddiFree support request or follow-up.",
                        "out_of_scope": (
                            "The message is a general-purpose chatbot request unrelated to DiddiFree support."
                        ),
                        "needs_human": (
                            "The message concerns safety, sensitive account action, or requires human judgment."
                        ),
                    },
                },
                "category": {
                    "type": "choice",
                    "instructions": "Which support category best describes the user's message?",
                    "criteria": {
                        "general": "General support or a complaint that does not fit another category.",
                        "account": "Account, profile, identity, or access problem.",
                        "payment": "Payment, charge, refund, balance, or transaction problem.",
                        "ride": "Ride, driver, or passenger problem.",
                        "delivery": "Delivery, courier, or package problem.",
                        "order": "Food, shop, order, or merchant problem.",
                        "safety": "Safety concern, threat, abuse, or urgent risk.",
                        "technical": "Technical problem with the DiddiFree application or service.",
                        "other": "A DiddiFree support request that does not fit the listed categories.",
                    },
                },
                "human_required": {
                    "type": "noul",
                    "instructions": "Does this message require a human support agent to review it?",
                    "criteria": {
                        "true": (
                            "The request needs human judgment, a sensitive action, or cannot be safely "
                            "handled by the AI."
                        ),
                        "false": "The AI can safely provide an informational support response.",
                    },
                },
            },
        }
        logger.info(
            "ai_decision_request_started",
            extra={"model": settings.jev_model, "history_count": len(state["history"])},
        )
        try:
            async with httpx.AsyncClient(
                base_url=settings.openrouter_base_url.rstrip("/"),
                timeout=settings.jev_timeout_seconds,
                transport=self.transport,
            ) as client:
                response = await client.post(
                    "../alpha/decisions",
                    json=payload,
                    headers={"Authorization": f"Bearer {settings.openrouter_api_key}"},
                )
                response.raise_for_status()
                data = response.json()
            logger.info("ai_decision_response_received", extra={"model": settings.jev_model})
            result = self._parse(data)
            if result.confidence < settings.decision_gate_confidence_threshold or result.human_required:
                return DecisionGateResult("needs_human", result.category, result.confidence, True)
            return result
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
            logger.exception(
                "ai_decision_request_failed",
                extra={"model": settings.jev_model, "error_type": type(exc).__name__},
            )
            raise DecisionGateError("Jev decision failed") from exc

    @staticmethod
    def _parse(data: dict[str, Any]) -> DecisionGateResult:
        answers = data["answers"]
        route_answer = answers["route"]
        category_answer = answers["category"]
        human_answer = answers["human_required"]
        route = str(route_answer.get("choice", route_answer.get("value")))
        category = str(category_answer.get("choice", category_answer.get("value")))
        confidence = float(
            data.get(
                "confidence",
                route_answer.get("confidence", route_answer.get("probability", 0)),
            )
        )
        human_value = human_answer.get("noul", human_answer.get("value", False))
        human_required = human_value if isinstance(human_value, bool) else float(human_value) >= 0.5
        if route not in {"support_allowed", "out_of_scope", "needs_human"}:
            raise ValueError("invalid route")
        return DecisionGateResult(route, category, confidence, human_required)
