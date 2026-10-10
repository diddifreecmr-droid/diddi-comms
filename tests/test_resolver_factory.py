from app_base.core.settings import Settings
from app_base.modules.context.infra.factory import resolver_for_owner


def test_resolver_factory_uses_configured_owner_registry() -> None:
    settings = Settings(
        owner_service_resolvers_json='{"custom-owner":{"base_url":"https://owner.test","client_id":"diddicomms-local-owner","client_secret":"secret","audience":"custom-owner","scope":"custom-owner:comms-task:read"}}',
        identity_service_token_url="https://identity.test/identity/v1/auth/service/token",
    )

    resolver = resolver_for_owner("custom-owner", settings)

    assert resolver.config.name == "custom-owner"
    assert resolver.config.base_url == "https://owner.test"
    assert resolver.config.context_scope == "custom-owner:comms-task:read"
