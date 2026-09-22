import json

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


@respx.mock
async def test_ensure_category_skips_if_already_present():
    respx.get("https://api.example.com/v1/categories").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "public_id": "11111111-1111-1111-1111-111111111111",
                    "name": "pulizia",
                    "created_at": "2026-01-01T00:00:00Z",
                    "updated_at": "2026-01-01T00:00:00Z",
                    "version": 1,
                }
            ],
        )
    )
    create_route = respx.post("https://api.example.com/v1/categories")
    client = RestrackitClient(_settings(), _FakeTokenProvider())

    await client.ensure_category("Pulizia")

    assert not create_route.called


@respx.mock
async def test_ensure_category_creates_if_missing():
    respx.get("https://api.example.com/v1/categories").mock(
        return_value=httpx.Response(200, json=[])
    )
    create_route = respx.post("https://api.example.com/v1/categories").mock(
        return_value=httpx.Response(
            201,
            json={
                "public_id": "1",
                "name": "pulizia",
                "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-01-01T00:00:00Z",
                "version": 1,
            },
        )
    )
    client = RestrackitClient(_settings(), _FakeTokenProvider())

    await client.ensure_category("Pulizia")

    assert create_route.called
    assert create_route.calls.last.request.content == b'{"name":"Pulizia"}'


@respx.mock
async def test_ensure_product_bulk_loads_then_resolves_public_id():
    bulk_route = respx.post("https://api.example.com/v1/products/bulk-load").mock(
        return_value=httpx.Response(
            201, json={"status": "ok", "messaggio": "ok", "riepilogo": {"nuovi_inseriti": 1, "gia_presenti": 0}}
        )
    )
    respx.get("https://api.example.com/v1/products/list", params={"category": "pasta"}).mock(
        return_value=httpx.Response(
            200,
            json={
                "items": [
                    {
                        "public_id": "22222222-2222-2222-2222-222222222222",
                        "name": "Pasta di semola",
                        "category": "pasta",
                        "allergen_mask": 0,
                        "allergens": [],
                        "gluten_free": False,
                        "created_at": "2026-01-01T00:00:00Z",
                        "updated_at": "2026-01-01T00:00:00Z",
                        "version": 1,
                    }
                ]
            },
        )
    )
    client = RestrackitClient(_settings(), _FakeTokenProvider())

    public_id = await client.ensure_product("Pasta di semola", "pasta")

    assert public_id == "22222222-2222-2222-2222-222222222222"
    assert bulk_route.called


@respx.mock
async def test_ensure_product_raises_if_not_found_after_load():
    respx.post("https://api.example.com/v1/products/bulk-load").mock(
        return_value=httpx.Response(
            201, json={"status": "ok", "messaggio": "ok", "riepilogo": {"nuovi_inseriti": 1, "gia_presenti": 0}}
        )
    )
    respx.get("https://api.example.com/v1/products/list", params={"category": "pasta"}).mock(
        return_value=httpx.Response(200, json={"items": []})
    )
    client = RestrackitClient(_settings(), _FakeTokenProvider())

    with pytest.raises(LookupError):
        await client.ensure_product("Pasta di semola", "pasta")


@respx.mock
async def test_ensure_storage_rule_creates_with_default_duration():
    route = respx.post(
        "https://api.example.com/v1/products/22222222-2222-2222-2222-222222222222/storage-rules"
    ).mock(return_value=httpx.Response(201, json={"public_id": "1"}))
    client = RestrackitClient(_settings(), _FakeTokenProvider())

    await client.ensure_storage_rule(
        "22222222-2222-2222-2222-222222222222",
        "33333333-3333-3333-3333-333333333333",
        "frigo",
    )

    sent = route.calls.last.request
    body = json.loads(sent.content)
    assert body == {
        "storage_method_public_id": "33333333-3333-3333-3333-333333333333",
        "duration_days": 7,
        "duration_hours": 0,
    }


@respx.mock
async def test_ensure_storage_rule_ignores_already_exists():
    respx.post(
        "https://api.example.com/v1/products/22222222-2222-2222-2222-222222222222/storage-rules"
    ).mock(
        return_value=httpx.Response(
            409, json={"error": {"code": "ERR_BUS_004", "message": "già esiste"}}
        )
    )
    client = RestrackitClient(_settings(), _FakeTokenProvider())

    await client.ensure_storage_rule(
        "22222222-2222-2222-2222-222222222222",
        "33333333-3333-3333-3333-333333333333",
        "frigo",
    )  # must not raise


@respx.mock
async def test_ensure_storage_rule_uses_generic_default_for_unknown_storage_method():
    route = respx.post(
        "https://api.example.com/v1/products/22222222-2222-2222-2222-222222222222/storage-rules"
    ).mock(return_value=httpx.Response(201, json={"public_id": "1"}))
    client = RestrackitClient(_settings(), _FakeTokenProvider())

    await client.ensure_storage_rule(
        "22222222-2222-2222-2222-222222222222",
        "55555555-5555-5555-5555-555555555555",
        "cantina",
    )

    body = json.loads(route.calls.last.request.content)
    assert body == {
        "storage_method_public_id": "55555555-5555-5555-5555-555555555555",
        "duration_days": 180,
        "duration_hours": 0,
    }
