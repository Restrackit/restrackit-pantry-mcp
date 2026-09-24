import pydantic
import pytest

from pantry_mcp.config import get_settings


def test_settings_load_from_env(monkeypatch):
    monkeypatch.setenv("KEYCLOAK_URL", "https://kc.example.com")
    monkeypatch.setenv("KEYCLOAK_REALM", "restrackit")
    monkeypatch.setenv("KEYCLOAK_CONNECTOR_CLIENT_ID", "restrackit-core")
    monkeypatch.setenv("KEYCLOAK_EXCHANGE_CLIENT_ID", "pantry-mcp-exchange")
    monkeypatch.setenv("KEYCLOAK_EXCHANGE_CLIENT_SECRET", "s3cr3t")
    monkeypatch.setenv("RESTRACKIT_BASE_URL", "https://api.example.com/v1")
    get_settings.cache_clear()

    settings = get_settings()

    assert settings.keycloak_url == "https://kc.example.com"
    assert settings.keycloak_connector_client_id == "restrackit-core"


def test_settings_missing_var_raises(monkeypatch):
    monkeypatch.delenv("KEYCLOAK_URL", raising=False)
    get_settings.cache_clear()

    with pytest.raises(pydantic.ValidationError):
        get_settings()


def test_settings_reads_token_exchange_fields(monkeypatch):
    monkeypatch.setenv("KEYCLOAK_URL", "https://kc.example.com")
    monkeypatch.setenv("KEYCLOAK_REALM", "restrackit")
    monkeypatch.setenv("KEYCLOAK_CONNECTOR_CLIENT_ID", "pantry-mcp-connector")
    monkeypatch.setenv("KEYCLOAK_EXCHANGE_CLIENT_ID", "pantry-mcp-token-exchange")
    monkeypatch.setenv("KEYCLOAK_EXCHANGE_CLIENT_SECRET", "s3cr3t")
    monkeypatch.setenv("RESTRACKIT_BASE_URL", "https://api.example.com/v1")
    get_settings.cache_clear()

    settings = get_settings()

    assert settings.keycloak_connector_client_id == "pantry-mcp-connector"
    assert settings.keycloak_exchange_client_id == "pantry-mcp-token-exchange"
    assert settings.keycloak_exchange_client_secret == "s3cr3t"
