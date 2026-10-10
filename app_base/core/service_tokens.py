from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

import httpx

from app_base.core.errors import ApiError


@dataclass
class ServiceTokenClient:
    token_url: str
    client_id: str
    client_secret: str
    audience: str
    timeout_seconds: float = 5.0
    transport: httpx.AsyncBaseTransport | None = None
    _tokens: dict[str, tuple[str, float]] = field(default_factory=dict, init=False, repr=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)

    async def access_token(self, scope: str) -> str:
        now = time.monotonic()
        cached = self._tokens.get(scope)
        if cached and now < cached[1]:
            return cached[0]

        async with self._lock:
            now = time.monotonic()
            cached = self._tokens.get(scope)
            if cached and now < cached[1]:
                return cached[0]

            try:
                async with httpx.AsyncClient(timeout=self.timeout_seconds, transport=self.transport) as client:
                    response = await client.post(
                        self.token_url,
                        headers={"X-Client-ID": self.client_id},
                        data={
                            "grant_type": "client_credentials",
                            "client_id": self.client_id,
                            "client_secret": self.client_secret,
                            "audience": self.audience,
                            "scope": scope,
                        },
                    )
                    response.raise_for_status()
                    payload = response.json()
                token = payload["access_token"]
                if not isinstance(token, str) or not token:
                    raise ValueError("token response does not contain access_token")
                expires_in = max(int(payload.get("expires_in", 600)), 1)
            except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
                raise ApiError(
                    502,
                    "SERVICE_TOKEN_UNAVAILABLE",
                    "Could not acquire a service token from DiddiFreeID.",
                ) from exc

            self._tokens[scope] = (token, time.monotonic() + max(expires_in - 30, 1))
            return token
