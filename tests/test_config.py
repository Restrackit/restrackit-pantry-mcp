import pydantic
import pytest

from pantry_mcp.config import get_settings


def test_settings_load_from_env(monkeypatch):
    monkeypatch.setenv("KEYCLOAK_URL", "https://kc.example.com")
    monkeypatch.setenv("KEYCLOAK_REALM", "restrackit")
    monkeypatch.setenv("KEYCLOAK_CLIENT_ID", "restrackit-core")
    monkeypatch.setenv("KEYCLOAK_USERNAME", "restrackit-pantry-mcp")
    monkeypatch.setenv("KEYCLOAK_PASSWORD", "secret")
    monkeypatch.setenv("RESTRACKIT_BASE_URL", "https://api.example.com/v1")
    monkeypatch.setenv("RESTRACKIT_STORE_ID", "1")
    monkeypatch.setenv("MCP_AUTH_TOKEN", "token123")
    get_settings.cache_clear()

    settings = get_settings()

    assert settings.keycloak_url == "https://kc.example.com"
    assert settings.restrackit_store_id == 1
    assert settings.mcp_auth_token == "token123"


def test_settings_missing_var_raises(monkeypatch):
    monkeypatch.delenv("KEYCLOAK_URL", raising=False)
    get_settings.cache_clear()

    with pytest.raises(pydantic.ValidationError):
        get_settings()
