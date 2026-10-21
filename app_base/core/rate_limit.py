from __future__ import annotations

from typing import Any

from fastapi import Request

from app_base.core.errors import ApiError
from app_base.core.metrics import increment
from app_base.core.settings import settings

_FIXED_WINDOW_SCRIPT = """
local current = redis.call('INCR', KEYS[1])
if current == 1 then
  redis.call('EXPIRE', KEYS[1], ARGV[1])
end
local ttl = redis.call('TTL', KEYS[1])
return {current, ttl}
"""


async def enforce_rate_limit(
    request: Request,
    *,
    bucket: str,
    subject: str,
    limit: int,
    window_seconds: int,
) -> None:
    redis: Any = getattr(request.app.state, "redis", None)
    if redis is None:
        if settings.environment == "production":
            raise ApiError(503, "RATE_LIMITER_UNAVAILABLE", "Rate limiting is temporarily unavailable.")
        return
    key = settings.redis_key(f"rate:{bucket}:{subject}")
    current, ttl = await redis.eval(_FIXED_WINDOW_SCRIPT, 1, key, window_seconds)
    if int(current) > limit:
        retry_after = max(int(ttl), 1)
        operation, _, dimension = bucket.partition(":")
        increment(
            "diddicomms_rate_limit_denials_total",
            {"operation": operation, "dimension": dimension or "unspecified"},
        )
        raise ApiError(
            429,
            "RATE_LIMIT_EXCEEDED",
            "Too many requests. Retry after the indicated delay.",
            headers={"Retry-After": str(retry_after)},
        )


async def enforce_user_conversation_limits(
    request: Request,
    *,
    operation: str,
    user_id: str,
    conversation_id: str,
    limit: int,
    window_seconds: int,
) -> None:
    client_ip = request.client.host if request.client else "unknown"
    for dimension, subject in (
        ("user", user_id),
        ("conversation", conversation_id),
        ("ip", client_ip),
    ):
        await enforce_rate_limit(
            request,
            bucket=f"{operation}:{dimension}",
            subject=subject,
            limit=limit,
            window_seconds=window_seconds,
        )
