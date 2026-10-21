from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)
_configured = False


def configure_tracing(app: FastAPI, engine: AsyncEngine, *, endpoint: str | None, service_name: str) -> bool:
    """Enable OTLP tracing only when an exporter endpoint is configured."""
    provider = _configure_dependencies(engine, endpoint=endpoint, service_name=service_name)
    if provider is None:
        return False

    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

    FastAPIInstrumentor.instrument_app(app, tracer_provider=provider)
    return True


def configure_worker_tracing(engine: AsyncEngine, *, endpoint: str | None, service_name: str) -> bool:
    """Enable dependency traces in the worker process when OTLP is configured."""
    return _configure_dependencies(engine, endpoint=endpoint, service_name=service_name) is not None


def _configure_dependencies(engine: AsyncEngine, *, endpoint: str | None, service_name: str) -> Any | None:
    global _configured
    if not endpoint or _configured:
        return None

    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
    from opentelemetry.instrumentation.redis import RedisInstrumentor
    from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    resource = Resource.create({"service.name": service_name, "service.namespace": "diddi"})
    provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter(endpoint=_trace_endpoint(endpoint))
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    HTTPXClientInstrumentor().instrument(tracer_provider=provider)
    RedisInstrumentor().instrument(tracer_provider=provider)
    SQLAlchemyInstrumentor().instrument(engine=engine.sync_engine, tracer_provider=provider)
    _configured = True
    logger.info("otel_tracing_enabled")
    return provider


def _trace_endpoint(endpoint: str) -> str:
    normalized = endpoint.rstrip("/")
    return normalized if normalized.endswith("/v1/traces") else f"{normalized}/v1/traces"
