import httpx
import respx

from pantry_mcp.auth import TokenExchanger
from pantry_mcp.config import Settings


# Valore diverso da "restrackit-backend" di proposito: prova che l'audience
# inviata a Keycloak proviene dalla config, non da una stringa hardcoded nel
# codice di TokenExchanger (verificato da test_exchange_posts_token_exchange_grant
# insieme a test_exchange_uses_configured_audience, che invece la imposta a
# "restrackit-backend").
def _settings(*, backend_client_id: str = "some-other-audience") -> Settings:
    return Settings(
        keycloak_url="https://kc.example.com",
        keycloak_realm="restrackit",
        keycloak_connector_client_id="pantry-mcp-connector",
        keycloak_exchange_client_id="pantry-mcp-token-exchange",
        keycloak_exchange_client_secret="exchanger-secret",
        restrackit_backend_client_id=backend_client_id,
        restrackit_base_url="https://api.example.com/v1",
    )


@respx.mock
async def test_exchange_posts_token_exchange_grant():
    route = respx.post(
        "https://kc.example.com/realms/restrackit/protocol/openid-connect/token"
    ).mock(
        return_value=httpx.Response(
            200, json={"access_token": "exchanged", "expires_in": 300}
        )
    )

    exchanger = TokenExchanger(_settings())
    token = await exchanger.exchange("user-token-abc")

    assert token == "exchanged"
    sent = route.calls.last.request.content.decode()
    assert (
        "grant_type=urn%3Aietf%3Aparams%3Aoauth%3Agrant-type%3Atoken-exchange" in sent
    )
    assert "subject_token=user-token-abc" in sent
    assert "audience=restrackit-backend" not in sent  # non hardcoded: verificato sotto
    assert "client_id=pantry-mcp-token-exchange" in sent
    assert "client_secret=exchanger-secret" in sent


@respx.mock
async def test_exchange_uses_configured_audience():
    route = respx.post(
        "https://kc.example.com/realms/restrackit/protocol/openid-connect/token"
    ).mock(
        return_value=httpx.Response(
            200, json={"access_token": "exchanged", "expires_in": 300}
        )
    )

    await TokenExchanger(_settings(backend_client_id="restrackit-backend")).exchange(
        "user-token-abc"
    )

    sent = route.calls.last.request.content.decode()
    assert "audience=restrackit-backend" in sent


@respx.mock
async def test_exchange_caches_per_user_token_before_expiry():
    route = respx.post(
        "https://kc.example.com/realms/restrackit/protocol/openid-connect/token"
    ).mock(
        return_value=httpx.Response(
            200, json={"access_token": "exchanged", "expires_in": 300}
        )
    )

    exchanger = TokenExchanger(_settings())
    await exchanger.exchange("user-token-abc")
    await exchanger.exchange("user-token-abc")

    assert route.call_count == 1


@respx.mock
async def test_exchange_does_not_share_cache_across_different_user_tokens():
    respx.post(
        "https://kc.example.com/realms/restrackit/protocol/openid-connect/token"
    ).mock(
        side_effect=[
            httpx.Response(200, json={"access_token": "for-user-a", "expires_in": 300}),
            httpx.Response(200, json={"access_token": "for-user-b", "expires_in": 300}),
        ]
    )

    exchanger = TokenExchanger(_settings())
    first = await exchanger.exchange("user-token-a")
    second = await exchanger.exchange("user-token-b")

    assert first == "for-user-a"
    assert second == "for-user-b"


@respx.mock
async def test_exchange_raises_on_keycloak_error_response():
    respx.post(
        "https://kc.example.com/realms/restrackit/protocol/openid-connect/token"
    ).mock(return_value=httpx.Response(400, json={"error": "invalid_target"}))

    exchanger = TokenExchanger(_settings())
    try:
        await exchanger.exchange("user-token-abc")
        raise AssertionError("expected httpx.HTTPStatusError")
    except httpx.HTTPStatusError:
        pass
