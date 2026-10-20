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

    owner_service_resolvers_json: str = "{}"

    otel_exporter_otlp_endpoint: str | None = None

    task_conversation_grace_minutes: int = Field(default=60, ge=0)
    message_retention_days: int = Field(default=180, gt=0)
    outbox_max_attempts: int = Field(default=5, ge=1, le=20)

    @model_validator(mode="after")
    def validate_security_baseline(self) -> Settings:
        if self.api_prefix != "/comms/v1":
            raise ValueError("API_PREFIX must remain /comms/v1 for the DiddiComms MVP contract")
        if self.environment == "production" and self.metrics_bearer_token == "local-dev-metrics-token":
            raise ValueError("production must not use the local development metrics token")
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
