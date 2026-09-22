import httpx
import pytest
import respx

from pantry_mcp.auth import TokenProvider
from pantry_mcp.config import Settings


def _settings() -> Settings:
    return Settings(
        keycloak_url="https://kc.example.com",
        keycloak_realm="restrackit",
        keycloak_client_id="restrackit-core",
        keycloak_username="restrackit-pantry-mcp",
        keycloak_password="secret",
        restrackit_base_url="https://api.example.com/v1",
        restrackit_store_id=1,
        mcp_auth_token="token123",
    )


@respx.mock
async def test_get_token_fetches_and_returns_access_token():
    route = respx.post(
        "https://kc.example.com/realms/restrackit/protocol/openid-connect/token"
    ).mock(return_value=httpx.Response(200, json={"access_token": "abc", "expires_in": 300}))

    provider = TokenProvider(_settings())
    token = await provider.get_token()

    assert token == "abc"
    assert route.called


@respx.mock
async def test_get_token_uses_cache_before_expiry():
    route = respx.post(
        "https://kc.example.com/realms/restrackit/protocol/openid-connect/token"
    ).mock(return_value=httpx.Response(200, json={"access_token": "abc", "expires_in": 300}))

    provider = TokenProvider(_settings())
    await provider.get_token()
    await provider.get_token()

    assert route.call_count == 1
