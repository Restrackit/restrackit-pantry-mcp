import httpx
import pytest
import respx

from pantry_mcp.config import Settings
from pantry_mcp.restrackit_client import RestrackitApiError, RestrackitClient, is_already_exists


def _settings() -> Settings:
    return Settings(
        keycloak_url="https://kc.example.com",
        keycloak_realm="restrackit",
        keycloak_client_id="restrackit-core",
        keycloak_username="restrackit-pantry-mcp",
        keycloak_password="secret",
        restrackit_base_url="https://api.example.com/v1",
        restrackit_store_id=42,
        mcp_auth_token="token123",
    )


class _FakeTokenProvider:
    async def get_token(self) -> str:
        return "fake-jwt"


@respx.mock
async def test_request_injects_auth_and_store_header():
    route = respx.get("https://api.example.com/v1/categories").mock(
        return_value=httpx.Response(200, json=[])
    )
    client = RestrackitClient(_settings(), _FakeTokenProvider())

    await client.request("GET", "/categories")

    sent = route.calls.last.request
    assert sent.headers["Authorization"] == "Bearer fake-jwt"
    assert sent.headers["X-Target-Store"] == "42"


@respx.mock
async def test_request_raises_on_error_body():
    respx.post("https://api.example.com/v1/categories").mock(
        return_value=httpx.Response(
            409,
            json={"error": {"code": "ERR_BUS_004", "message": "già esiste"}},
        )
    )
    client = RestrackitClient(_settings(), _FakeTokenProvider())

    with pytest.raises(RestrackitApiError) as exc_info:
        await client.request("POST", "/categories", json={"name": "pulizia"})

    assert exc_info.value.code == "ERR_BUS_004"
    assert exc_info.value.status_code == 409
    assert is_already_exists(exc_info.value)
