from __future__ import annotations

from app_base.core.service_tokens import ServiceTokenClient
from app_base.core.settings import Settings, settings
from app_base.modules.support.read_client import DiddiSupportReadClient, DiddiSupportReadConfig


def diddisupport_read_client(config: Settings = settings) -> DiddiSupportReadClient:
    missing = [
        name
        for name, value in {
            "DIDDISUPPORT_BASE_URL": config.diddisupport_base_url,
            "DIDDISUPPORT_CLIENT_ID": config.diddisupport_client_id,
            "DIDDISUPPORT_CLIENT_SECRET": config.diddisupport_client_secret,
            "IDENTITY_SERVICE_TOKEN_URL": config.identity_service_token_url,
        }.items()
        if not value
    ]
    if missing:
        raise ValueError(f"DiddiSupport client is not configured: missing {', '.join(missing)}")

    token_client = ServiceTokenClient(
        token_url=str(config.identity_service_token_url),
        client_id=str(config.diddisupport_client_id),
        client_secret=str(config.diddisupport_client_secret),
        audience=config.diddisupport_audience,
        timeout_seconds=config.identity_http_timeout_seconds,
    )
    return DiddiSupportReadClient(
        DiddiSupportReadConfig(
            base_url=str(config.diddisupport_base_url),
            client_id=str(config.diddisupport_client_id),
            scope=config.diddisupport_scope,
            create_scope=config.diddisupport_create_scope,
            messages_scope=config.diddisupport_messages_scope,
            service_token_client=token_client,
        ),
        timeout_seconds=config.identity_http_timeout_seconds,
    )
