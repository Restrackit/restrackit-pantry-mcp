import httpx
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
        tenants_table_name="PantryMcpTenants",
    )


@respx.mock
async def test_get_token_fetches_and_returns_access_token():
    route = respx.post(
        "https://kc.example.com/realms/restrackit/protocol/openid-connect/token"
    ).mock(
        return_value=httpx.Response(
            200, json={"access_token": "abc", "expires_in": 300}
        )
    )

    provider = TokenProvider(_settings())
    token = await provider.get_token()

    assert token == "abc"
    assert route.called


@respx.mock
async def test_get_token_uses_cache_before_expiry():
    route = respx.post(
        "https://kc.example.com/realms/restrackit/protocol/openid-connect/token"
    ).mock(
        return_value=httpx.Response(
            200, json={"access_token": "abc", "expires_in": 300}
        )
    )

    provider = TokenProvider(_settings())
    await provider.get_token()
    await provider.get_token()

    assert route.call_count == 1


@respx.mock
async def test_get_token_refetches_after_expiry():
    route = respx.post(
        "https://kc.example.com/realms/restrackit/protocol/openid-connect/token"
    ).mock(
        side_effect=[
            httpx.Response(200, json={"access_token": "expired", "expires_in": -100}),
            httpx.Response(200, json={"access_token": "fresh", "expires_in": 300}),
        ]
    )

    provider = TokenProvider(_settings())
    first = await provider.get_token()
    second = await provider.get_token()

    assert first == "expired"
    assert second == "fresh"
    assert route.call_count == 2
