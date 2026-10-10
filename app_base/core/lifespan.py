from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app_base.core.database import ping_db
from app_base.core.redis import create_redis, ping_redis


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    redis = create_redis()
    app.state.redis = redis
    await ping_db()
    await ping_redis(redis)
    try:
        yield
    finally:
        await redis.aclose()

