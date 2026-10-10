from __future__ import annotations

import logging
from typing import Any

from redis.asyncio import Redis

from app_base.core.settings import settings

logger = logging.getLogger(__name__)


def create_redis() -> Redis:
    return Redis.from_url(settings.redis_url, decode_responses=True)


async def ping_redis(client: Redis) -> None:
    await client.ping()
    logger.info("redis reachable")


async def redis_ready(client: Any) -> bool:
    try:
        return client is not None and bool(await client.ping())
    except Exception:
        return False

