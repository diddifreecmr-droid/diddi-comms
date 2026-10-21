from __future__ import annotations

import json
from typing import Any

from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "DiddiComms"
    environment: str = Field(default="local", validation_alias=AliasChoices("ENVIRONMENT", "APP_ENV"))
    api_prefix: str = "/comms/v1"
    log_level: str = "INFO"

    database_url: str = "postgresql+asyncpg://diddicomms:diddicomms@localhost:15442/diddicomms_local"
    alembic_database_url: str = "postgresql+psycopg://diddicomms:diddicomms@localhost:15442/diddicomms_local"
    redis_url: str = "redis://localhost:16442/0"
    redis_key_prefix: str = "diddicomms"
    support_events_redis_url: str = ""

    metrics_bearer_token: str = "local-dev-metrics-token"

    identity_issuer: str = "diddifree-id"
    identity_audience: str = "diddicomms"
    identity_jwks_url: str | None = None
    identity_service_token_url: str | None = None
    identity_http_timeout_seconds: float = Field(default=5.0, gt=0, le=30)

    diddisupport_base_url: str | None = None
    diddisupport_client_id: str | None = None
    diddisupport_client_secret: str | None = None
    diddisupport_audience: str = "diddi-support"
    diddisupport_scope: str = "diddi-support:cases:read"
    diddisupport_create_scope: str = "diddi-support:cases:create"
    diddisupport_messages_scope: str = "diddi-support:messages:write"

    owner_service_resolvers_json: str = "{}"

    otel_exporter_otlp_endpoint: str | None = None

    task_conversation_grace_minutes: int = Field(default=60, ge=0)
    message_retention_days: int = Field(default=180, gt=0)
    outbox_max_attempts: int = Field(default=5, ge=1, le=20)
    worker_retry_max_seconds: int = Field(default=30, ge=1, le=300)
    worker_metrics_refresh_seconds: int = Field(default=10, ge=1, le=300)
    websocket_heartbeat_seconds: int = Field(default=15, ge=5, le=120)
    websocket_idle_timeout_seconds: int = Field(default=90, ge=15, le=900)
    websocket_max_connections_per_user: int = Field(default=5, ge=1, le=50)
    websocket_max_connections_per_conversation: int = Field(default=200, ge=1, le=5000)
    support_events_stream: str = "diddisupport.events"
    support_events_consumer_group: str = "diddicomms"
    support_events_consumer_name: str = ""
    inbound_events_dlq_stream: str = "diddicomms.inbound.dlq"
    event_consumer_max_attempts: int = Field(default=5, ge=1, le=20)
    event_consumer_reclaim_idle_ms: int = Field(default=60_000, ge=1_000)
    message_rate_limit_per_minute: int = Field(default=30, ge=1, le=1000)
    call_rate_limit_per_five_minutes: int = Field(default=5, ge=1, le=100)
    support_case_rate_limit_per_hour: int = Field(default=10, ge=1, le=100)
    events_stream_maxlen: int = Field(default=100_000, ge=1_000)
    events_dlq_stream_maxlen: int = Field(default=10_000, ge=100)

    @model_validator(mode="after")
    def validate_security_baseline(self) -> Settings:
        if self.api_prefix != "/comms/v1":
            raise ValueError("API_PREFIX must remain /comms/v1 for the DiddiComms MVP contract")
        if self.environment == "production" and self.metrics_bearer_token == "local-dev-metrics-token":
            raise ValueError("production must not use the local development metrics token")
        if self.websocket_idle_timeout_seconds <= self.websocket_heartbeat_seconds:
            raise ValueError("WEBSOCKET_IDLE_TIMEOUT_SECONDS must exceed WEBSOCKET_HEARTBEAT_SECONDS")
        return self

    def redis_key(self, suffix: str) -> str:
        return f"{self.redis_key_prefix}:{suffix}"

    def owner_service_resolvers(self) -> dict[str, Any]:
        from app_base.modules.context.infra.factory import ResolverSettings

        raw = json.loads(self.owner_service_resolvers_json)
        if not isinstance(raw, dict):
            raise ValueError("OWNER_SERVICE_RESOLVERS_JSON must be a JSON object")
        return {
            owner_service: ResolverSettings(
                base_url=str(values["base_url"]),
                client_id=str(values["client_id"]),
                client_secret=str(values["client_secret"]),
                audience=str(values["audience"]),
                scope=str(values["scope"]),
            )
            for owner_service, values in raw.items()
            if isinstance(values, dict)
        }


settings = Settings()
