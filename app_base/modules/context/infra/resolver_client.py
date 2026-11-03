from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

import httpx

from app_base.core.errors import ApiError
from app_base.core.request_context import current_request_id
from app_base.core.service_tokens import ServiceTokenClient
from app_base.modules.context.domain import CommunicationContext, ExternalName, TaskReference


@dataclass(frozen=True)
class OwnerServiceConfig:
    name: str
    base_url: str
    context_scope: str
    service_token_client: ServiceTokenClient


class ContextResolverClient:
    def __init__(
        self,
        config: OwnerServiceConfig,
        timeout_seconds: float = 5.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.config = config
        self.timeout_seconds = timeout_seconds
        self.transport = transport

    async def get_task(self, task_type: ExternalName, task_id: UUID) -> CommunicationContext:
        path = f"/internal/v1/comms/tasks/{task_type}/{task_id}"
        token = await self.config.service_token_client.access_token(self.config.context_scope)
        headers = {
            "Authorization": f"Bearer {token}",
            "X-Client-ID": self.config.service_token_client.client_id,
        }
        request_id = current_request_id()
        if request_id:
            headers["X-Request-ID"] = request_id
            headers["X-Correlation-ID"] = request_id

        try:
            async with httpx.AsyncClient(
                base_url=self.config.base_url.rstrip("/"),
                timeout=self.timeout_seconds,
                transport=self.transport,
            ) as client:
                response = await client.get(path, headers=headers)
                response.raise_for_status()
                payload = response.json()
            context = _parse_context_response(
                payload,
                owner_service=self.config.name,
                task_type=task_type,
                task_id=task_id,
            )
            expected = TaskReference(owner_service=self.config.name, task_type=task_type, task_id=task_id)
            if context.task != expected:
                raise ValueError("resolver response task reference does not match request")
            return context
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in {401, 403}:
                raise ApiError(
                    502,
                    "CONTEXT_RESOLVER_AUTH_REJECTED",
                    f"{self.config.name} rejected DiddiComms context authorization.",
                ) from exc
            if exc.response.status_code == 404:
                raise ApiError(404, "CONTEXT_NOT_FOUND", "Communication context was not found.") from exc
            raise ApiError(
                502,
                "CONTEXT_RESOLVER_REJECTED",
                f"{self.config.name} rejected the communication context request.",
            ) from exc
        except httpx.RequestError as exc:
            raise ApiError(
                503,
                "CONTEXT_RESOLVER_UNAVAILABLE",
                f"{self.config.name} context resolver is temporarily unavailable.",
            ) from exc
        except ValueError as exc:
            raise ApiError(
                502,
                "CONTEXT_RESOLVER_INVALID_RESPONSE",
                f"{self.config.name} returned an invalid context response.",
            ) from exc


def _parse_context_response(
    payload: object,
    *,
    owner_service: str,
    task_type: ExternalName,
    task_id: UUID,
) -> CommunicationContext:
    """Normalize the DiddiSend delivery-context contract to DiddiComms' domain."""
    if not isinstance(payload, dict) or not str(payload.get("contract_version", "")).startswith(
        "delivery-task-context."
    ):
        return CommunicationContext.model_validate(payload)

    task = payload.get("task")
    participants = payload.get("participants")
    policy = payload.get("communication_policy")
    if not isinstance(task, dict) or not isinstance(participants, list) or not isinstance(policy, dict):
        raise ValueError("delivery context sections are invalid")

    conversation_policy = policy.get("conversation")
    external_call_policy = policy.get("external_call")
    normalized_participants = []
    for participant in participants:
        if not isinstance(participant, dict):
            raise ValueError("delivery context participant is invalid")
        normalized_participants.append(
            {
                "user_id": participant["user_id"],
                "role": participant["role"],
            }
        )

    return CommunicationContext.model_validate(
        {
            "task": {
                "owner_service": owner_service,
                "task_type": task_type,
                "task_id": task_id,
            },
            "state": task["status"],
            "version": task.get("version", 0),
            "participants": normalized_participants,
            "messaging_allowed": conversation_policy == "active",
            "calling_allowed": external_call_policy == "request_via_diddicomms",
            "closes_at": payload.get("closes_at"),
        }
    )
