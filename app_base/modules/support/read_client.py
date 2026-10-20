from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

import httpx
from pydantic import BaseModel, ConfigDict

from app_base.core.errors import ApiError
from app_base.core.request_context import current_request_id
from app_base.core.service_tokens import ServiceTokenClient


class SupportContextResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    protocol: str
    origin_service: str
    resource_type: str
    resource_id: str
    data: dict[str, Any]
    redacted_fields: list[str]
    as_of: datetime
    fetched_at: datetime


class SupportCaseContextResponse(BaseModel):
    """Read contract returned by DiddiSupport for a case and its current context."""

    model_config = ConfigDict(extra="allow")

    case: dict[str, Any]
    context: SupportContextResponse | None = None


@dataclass(frozen=True)
class DiddiSupportReadConfig:
    base_url: str
    client_id: str
    scope: str
    service_token_client: ServiceTokenClient


class DiddiSupportReadClient:
    """Outbound, read-only client for DiddiSupport's internal contract."""

    def __init__(
        self,
        config: DiddiSupportReadConfig,
        timeout_seconds: float = 5.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.config = config
        self.timeout_seconds = timeout_seconds
        self.transport = transport

    async def get_context(
        self, origin_service: str, resource_type: str, resource_id: UUID | str
    ) -> SupportContextResponse:
        path = f"/support/v1/internal/context/{origin_service}/{resource_type}/{resource_id}"
        payload = await self._get(path)
        try:
            return SupportContextResponse.model_validate(payload)
        except ValueError as exc:
            raise ApiError(
                502, "DIDDISUPPORT_INVALID_RESPONSE", "DiddiSupport returned an invalid context response."
            ) from exc

    async def get_case_context(self, case_id: UUID | str) -> SupportCaseContextResponse:
        path = f"/support/v1/internal/cases/{case_id}/context"
        payload = await self._get(path)
        try:
            return SupportCaseContextResponse.model_validate(payload)
        except ValueError as exc:
            raise ApiError(
                502, "DIDDISUPPORT_INVALID_RESPONSE", "DiddiSupport returned an invalid case context response."
            ) from exc

    async def _get(self, path: str) -> dict[str, Any]:
        token = await self.config.service_token_client.access_token(self.config.scope)
        headers = {
            "Authorization": f"Bearer {token}",
            "X-Client-ID": self.config.client_id,
            "X-Request-ID": current_request_id() or str(uuid4()),
        }
        try:
            async with httpx.AsyncClient(
                base_url=self.config.base_url.rstrip("/"),
                timeout=self.timeout_seconds,
                transport=self.transport,
            ) as client:
                response = await client.get(path, headers=headers)
                response.raise_for_status()
                payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("response is not an object")
            return payload
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status == 401:
                raise ApiError(502, "DIDDISUPPORT_AUTH_REJECTED", "DiddiSupport rejected the service token.") from exc
            if status == 403:
                code = "DIDDISUPPORT_SCOPE_FORBIDDEN"
                with suppress(ValueError, AttributeError, TypeError):
                    code = exc.response.json().get("error", {}).get("code", code)
                raise ApiError(502, code, "DiddiComms is not authorized to read DiddiSupport data.") from exc
            if status == 404:
                raise ApiError(
                    404, "DIDDISUPPORT_NOT_FOUND", "The requested DiddiSupport resource was not found."
                ) from exc
            if status == 503:
                raise ApiError(503, "DIDDISUPPORT_UNAVAILABLE", "DiddiSupport is temporarily unavailable.") from exc
            raise ApiError(502, "DIDDISUPPORT_REQUEST_REJECTED", "DiddiSupport rejected the read request.") from exc
        except httpx.RequestError as exc:
            raise ApiError(503, "DIDDISUPPORT_UNAVAILABLE", "DiddiSupport is temporarily unavailable.") from exc
        except ValueError as exc:
            raise ApiError(502, "DIDDISUPPORT_INVALID_RESPONSE", "DiddiSupport returned invalid JSON.") from exc
