from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse, Response
from redis.exceptions import RedisError
from sqlalchemy.exc import SQLAlchemyError

from app_base.core.database import database_ready, engine
from app_base.core.errors import ApiError, api_error_handler, infrastructure_error_handler, unhandled_exception_handler
from app_base.core.lifespan import lifespan
from app_base.core.metrics import render_prometheus, render_shared_metrics
from app_base.core.observability import configure_logging
from app_base.core.redis import redis_ready
from app_base.core.request_logging import RequestLoggingMiddleware
from app_base.core.security import require_metrics_token
from app_base.core.settings import settings
from app_base.core.tracing import configure_tracing
from app_base.modules.conversations.presentation.router import router as conversations_router
from app_base.modules.platform.presentation.router import router as platform_router
from app_base.modules.realtime.router import router as realtime_router

configure_logging(settings.log_level)

app = FastAPI(title=settings.app_name, lifespan=lifespan)
configure_tracing(app, engine, endpoint=settings.otel_exporter_otlp_endpoint, service_name=settings.app_name)
app.add_middleware(RequestLoggingMiddleware)
app.add_exception_handler(ApiError, api_error_handler)
app.add_exception_handler(SQLAlchemyError, infrastructure_error_handler)
app.add_exception_handler(RedisError, infrastructure_error_handler)
app.add_exception_handler(Exception, unhandled_exception_handler)

app.include_router(platform_router, prefix=settings.api_prefix)
app.include_router(conversations_router, prefix=settings.api_prefix)
app.include_router(realtime_router, prefix=settings.api_prefix)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "app": settings.app_name}


@app.get("/ready")
async def readiness(request: Request) -> Response:
    db_ok = await database_ready()
    redis_ok = await redis_ready(getattr(request.app.state, "redis", None))
    ready = db_ok and redis_ok
    payload = {
        "status": "ready" if ready else "not_ready",
        "app": settings.app_name,
        "components": {
            "database": "ok" if db_ok else "unavailable",
            "redis": "ok" if redis_ok else "unavailable",
        },
    }
    return JSONResponse(status_code=200 if ready else 503, content=payload)


@app.get("/internal/metrics", include_in_schema=False)
async def metrics(request: Request, _: None = Depends(require_metrics_token)) -> Response:
    shared = await render_shared_metrics(
        getattr(request.app.state, "redis", None),
        settings.redis_key("metrics:worker"),
    )
    return Response(render_prometheus() + shared, media_type="text/plain; version=0.0.4; charset=utf-8")
