from unittest.mock import MagicMock, patch

import pydantic
import pytest

from pantry_mcp.config import get_settings


def test_settings_load_from_env(monkeypatch):
    monkeypatch.setenv("KEYCLOAK_URL", "https://kc.example.com")
    monkeypatch.setenv("KEYCLOAK_REALM", "restrackit")
    monkeypatch.setenv("KEYCLOAK_CONNECTOR_CLIENT_ID", "restrackit-core")
    monkeypatch.setenv("KEYCLOAK_EXCHANGE_CLIENT_ID", "pantry-mcp-exchange")
    monkeypatch.setenv("KEYCLOAK_EXCHANGE_CLIENT_SECRET", "s3cr3t")
    monkeypatch.setenv("RESTRACKIT_BACKEND_CLIENT_ID", "restrackit-backend")
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
    monkeypatch.setenv("RESTRACKIT_BACKEND_CLIENT_ID", "restrackit-backend")
    monkeypatch.setenv("RESTRACKIT_BASE_URL", "https://api.example.com/v1")
    get_settings.cache_clear()

    settings = get_settings()

    assert settings.keycloak_connector_client_id == "pantry-mcp-connector"
    assert settings.keycloak_exchange_client_id == "pantry-mcp-token-exchange"
    assert settings.keycloak_exchange_client_secret == "s3cr3t"
    assert settings.restrackit_backend_client_id == "restrackit-backend"


def _set_base_env(monkeypatch):
    monkeypatch.setenv("KEYCLOAK_URL", "https://kc.example.com")
    monkeypatch.setenv("KEYCLOAK_REALM", "restrackit")
    monkeypatch.setenv("KEYCLOAK_CONNECTOR_CLIENT_ID", "restrackit-core")
    monkeypatch.setenv("KEYCLOAK_EXCHANGE_CLIENT_ID", "pantry-mcp-exchange")
    monkeypatch.setenv("RESTRACKIT_BACKEND_CLIENT_ID", "restrackit-backend")
    monkeypatch.setenv("RESTRACKIT_BASE_URL", "https://api.example.com/v1")


def test_settings_with_direct_secret_does_not_call_secrets_manager(monkeypatch):
    """When the secret is provided directly, Secrets Manager must never be hit."""
    _set_base_env(monkeypatch)
    monkeypatch.setenv("KEYCLOAK_EXCHANGE_CLIENT_SECRET", "s3cr3t")
    monkeypatch.delenv("KEYCLOAK_EXCHANGE_CLIENT_SECRET_NAME", raising=False)
    get_settings.cache_clear()

    with patch("pantry_mcp.config.boto3.client") as mock_client:
        # If the validator wrongly called Secrets Manager, this would overwrite
        # the direct value and the assertion below would fail.
        mock_client.return_value.get_secret_value.return_value = {
            "SecretString": "wrong-value-from-sm"
        }
        settings = get_settings()

    mock_client.assert_not_called()
    assert settings.keycloak_exchange_client_secret == "s3cr3t"
    get_settings.cache_clear()


def test_settings_resolves_secret_from_secrets_manager_by_name(monkeypatch):
    """When only the secret NAME is set, the validator fetches the value from SM."""
    _set_base_env(monkeypatch)
    monkeypatch.delenv("KEYCLOAK_EXCHANGE_CLIENT_SECRET", raising=False)
    monkeypatch.setenv("KEYCLOAK_EXCHANGE_CLIENT_SECRET_NAME", "pantry-mcp/token-exchange-client")
    get_settings.cache_clear()

    mock_client = MagicMock()
    mock_client.get_secret_value.return_value = {"SecretString": "secret-from-sm"}
    with patch("pantry_mcp.config.boto3.client", return_value=mock_client) as mock_boto_client:
        settings = get_settings()

    mock_boto_client.assert_called_once_with("secretsmanager")
    mock_client.get_secret_value.assert_called_once_with(
        SecretId="pantry-mcp/token-exchange-client"
    )
    assert settings.keycloak_exchange_client_secret == "secret-from-sm"
    get_settings.cache_clear()
