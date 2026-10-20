import pytest

from app_base.core.settings import Settings


def test_phase_zero_contract_defaults() -> None:
    settings = Settings()

    assert settings.app_name == "DiddiComms"
    assert settings.api_prefix == "/comms/v1"
    assert settings.identity_audience == "diddicomms"
    assert settings.identity_issuer == "diddifree-id"
    assert settings.diddisupport_audience == "diddi-support"
    assert settings.diddisupport_scope == "diddi-support:cases:read"
    assert settings.diddisupport_create_scope == "diddi-support:cases:create"
    assert settings.diddisupport_messages_scope == "diddi-support:messages:write"


def test_production_rejects_local_metrics_token() -> None:
    with pytest.raises(ValueError, match="production must not use"):
        Settings(ENVIRONMENT="production")

