from __future__ import annotations

from dataclasses import dataclass

from app_base.core.service_tokens import ServiceTokenClient
from app_base.core.settings import Settings, settings
from app_base.modules.context.infra.resolver_client import ContextResolverClient, OwnerServiceConfig


@dataclass(frozen=True)
class ResolverSettings:
    base_url: str
    client_id: str
    client_secret: str
    audience: str
    scope: str


def resolver_for_owner(owner_service: str, config: Settings = settings) -> ContextResolverClient:
    resolvers = config.owner_service_resolvers()
    if owner_service not in resolvers:
        raise ValueError(f"owner service resolver is not configured: {owner_service}")
    return _resolver(name=owner_service, resolver=resolvers[owner_service], config=config)


def _resolver(
    *,
    name: str,
    resolver: ResolverSettings,
    config: Settings,
) -> ContextResolverClient:
    missing = [
        key
        for key, value in {
            "base_url": resolver.base_url,
            "service_client_id": resolver.client_id,
            "service_client_secret": resolver.client_secret,
            "identity_service_token_url": config.identity_service_token_url,
        }.items()
        if not value
    ]
    if missing:
        raise ValueError(f"{name} resolver is not configured: missing {', '.join(missing)}")
    token_client = ServiceTokenClient(
        token_url=str(config.identity_service_token_url),
        client_id=resolver.client_id,
        client_secret=resolver.client_secret,
        audience=resolver.audience,
        timeout_seconds=config.identity_http_timeout_seconds,
    )
    return ContextResolverClient(
        OwnerServiceConfig(
            name=name,
            base_url=resolver.base_url,
            context_scope=resolver.scope,
            service_token_client=token_client,
        ),
        timeout_seconds=config.identity_http_timeout_seconds,
    )
