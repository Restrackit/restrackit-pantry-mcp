import time

import httpx
import pytest
import respx
from starlette.testclient import TestClient

from pantry_mcp import server
from tests.test_jwks import (  # reuse helpers
    _jwk_from_public_key,
    _make_rsa_keypair,
    _sign_token,
)


@pytest.fixture(autouse=True)
def _settings_env(monkeypatch):
    monkeypatch.setenv("KEYCLOAK_URL", "https://kc.example.com")
    monkeypatch.setenv("KEYCLOAK_REALM", "restrackit")
    monkeypatch.setenv("KEYCLOAK_CONNECTOR_CLIENT_ID", "pantry-mcp-connector")
    monkeypatch.setenv("KEYCLOAK_EXCHANGE_CLIENT_ID", "pantry-mcp-token-exchange")
    monkeypatch.setenv("KEYCLOAK_EXCHANGE_CLIENT_SECRET", "exchanger-secret")
    monkeypatch.setenv("RESTRACKIT_BACKEND_CLIENT_ID", "restrackit-backend")
    monkeypatch.setenv("RESTRACKIT_BASE_URL", "https://api.example.com/v1")
    monkeypatch.setenv("MCP_PUBLIC_BASE_URL", "https://pantry-mcp.example.com")


def _keypair_and_jwks():
    private_key, public_key = _make_rsa_keypair()
    kid = "test-key-1"
    return private_key, kid, {"keys": [_jwk_from_public_key(public_key, kid)]}


def _user_token(private_key, kid, *, store_id="1", exp_delta=300):
    return _sign_token(
        private_key,
        kid,
        {
            "iss": "https://kc.example.com/realms/restrackit",
            "aud": "pantry-mcp-connector",
            "sub": "user-1",
            "store_id": [store_id],
            "exp": int(time.time()) + exp_delta,
        },
    )


def test_health_check_requires_no_auth():
    client = TestClient(server.app)
    response = client.get("/health")
    assert response.status_code == 200


def test_mcp_endpoint_allows_cors_preflight_without_auth():
    """Connector clients probe with an unauthenticated OPTIONS preflight first."""
    client = TestClient(server.app)

    response = client.options(
        "/mcp",
        headers={
            "Origin": "https://claude.ai",
            "Access-Control-Request-Method": "POST",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "*"


def test_mcp_endpoint_rejects_missing_bearer_token():
    client = TestClient(server.app)
    response = client.post("/mcp", json={})
    assert response.status_code == 401


def test_missing_bearer_token_includes_www_authenticate_header():
    """The 401 must carry a WWW-Authenticate hint so Claude can discover Keycloak (C1)."""
    client = TestClient(server.app)
    response = client.post("/mcp", json={})
    assert response.status_code == 401
    www_authenticate = response.headers["www-authenticate"]
    assert www_authenticate.startswith("Bearer ")
    assert (
        'resource_metadata="https://pantry-mcp.example.com/.well-known/'
        'oauth-protected-resource"' in www_authenticate
    )


def test_oauth_protected_resource_is_reachable_without_auth():
    """RFC 9728 discovery document must be servable with no Authorization header (C1)."""
    client = TestClient(server.app)
    response = client.get("/.well-known/oauth-protected-resource")

    assert response.status_code == 200
    body = response.json()
    assert body["resource"] == "https://pantry-mcp.example.com/mcp"
    assert body["authorization_servers"] == ["https://kc.example.com/realms/restrackit"]
    assert body["bearer_methods_supported"] == ["header"]


@respx.mock
def test_mcp_endpoint_rejects_expired_token():
    private_key, kid, jwks = _keypair_and_jwks()
    respx.get("https://kc.example.com/realms/restrackit/protocol/openid-connect/certs").mock(
        return_value=httpx.Response(200, json=jwks)
    )
    token = _user_token(private_key, kid, exp_delta=-10)

    client = TestClient(server.create_app())
    response = client.post("/mcp", json={}, headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 401
    assert "www-authenticate" in response.headers


@respx.mock
def test_mcp_endpoint_rejects_token_missing_store_id():
    private_key, kid, jwks = _keypair_and_jwks()
    respx.get("https://kc.example.com/realms/restrackit/protocol/openid-connect/certs").mock(
        return_value=httpx.Response(200, json=jwks)
    )
    token = _sign_token(
        private_key,
        kid,
        {
            "iss": "https://kc.example.com/realms/restrackit",
            "aud": "pantry-mcp-connector",
            "sub": "user-1",
            "exp": int(time.time()) + 300,
        },
    )

    client = TestClient(server.create_app())
    response = client.post("/mcp", json={}, headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 401


@respx.mock
def test_mcp_endpoint_rejects_non_numeric_store_id():
    private_key, kid, jwks = _keypair_and_jwks()
    respx.get("https://kc.example.com/realms/restrackit/protocol/openid-connect/certs").mock(
        return_value=httpx.Response(200, json=jwks)
    )
    token = _sign_token(
        private_key,
        kid,
        {
            "iss": "https://kc.example.com/realms/restrackit",
            "aud": "pantry-mcp-connector",
            "sub": "user-1",
            "store_id": ["not-a-number"],
            "exp": int(time.time()) + 300,
        },
    )

    client = TestClient(server.create_app())
    response = client.post("/mcp", json={}, headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 401


def test_mcp_handshake_lists_all_tools():
    private_key, kid, jwks = _keypair_and_jwks()
    with respx.mock:
        respx.get(
            "https://kc.example.com/realms/restrackit/protocol/openid-connect/certs"
        ).mock(return_value=httpx.Response(200, json=jwks))
        token = _user_token(private_key, kid)
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }

        with TestClient(server.create_app()) as client:
            init_response = client.post(
                "/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-06-18",
                        "capabilities": {},
                        "clientInfo": {"name": "test-client", "version": "0.1"},
                    },
                },
                headers=headers,
            )
            assert init_response.status_code == 200
            assert (
                init_response.json()["result"]["serverInfo"]["name"]
                == "restrackit-pantry-mcp"
            )

            list_response = client.post(
                "/mcp",
                json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
                headers=headers,
            )

    assert list_response.status_code == 200
    tool_names = {tool["name"] for tool in list_response.json()["result"]["tools"]}
    assert tool_names == {
        "add_purchase",
        "get_pantry_status",
        "record_consumption",
        "get_expiring_items",
    }


@respx.mock
def test_different_tokens_route_to_different_stores():
    private_key, kid, jwks = _keypair_and_jwks()
    respx.get("https://kc.example.com/realms/restrackit/protocol/openid-connect/certs").mock(
        return_value=httpx.Response(200, json=jwks)
    )
    respx.post("https://kc.example.com/realms/restrackit/protocol/openid-connect/token").mock(
        return_value=httpx.Response(200, json={"access_token": "exchanged", "expires_in": 300})
    )
    respx.get("https://api.example.com/v1/inventory/list").mock(
        return_value=httpx.Response(200, json={"status": "ok", "count": 0, "items": [], "next_cursor": None})
    )

    def _call(store_id):
        token = _user_token(private_key, kid, store_id=store_id)
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        with TestClient(server.create_app()) as client:
            client.post(
                "/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-06-18",
                        "capabilities": {},
                        "clientInfo": {"name": "test-client", "version": "0.1"},
                    },
                },
                headers=headers,
            )
            client.post(
                "/mcp",
                json={"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "get_pantry_status", "arguments": {}}},
                headers=headers,
            )

    _call("1")
    _call("2")

    sent_stores = [
        call.request.headers["X-Target-Store"]
        for call in respx.calls
        if call.request.url.path == "/v1/inventory/list"
    ]
    assert sent_stores == ["1", "2"]


def test_lambda_handler_wraps_health_check():
    from pantry_mcp.lambda_handler import handler

    event = {
        "version": "2.0",
        "routeKey": "GET /health",
        "rawPath": "/health",
        "headers": {},
        "requestContext": {
            "http": {"method": "GET", "path": "/health", "sourceIp": "127.0.0.1"}
        },
        "isBase64Encoded": False,
    }

    response = handler(event, None)

    assert response["statusCode"] == 200


def test_lambda_handler_survives_multiple_invocations():
    """A warm Lambda container serves many requests through the same handler.

    Regression test: mcp's StreamableHTTPSessionManager can only run its
    lifespan once per instance, so a handler built around a module-level app
    singleton crashes from the second invocation onward.
    """
    from pantry_mcp.lambda_handler import handler

    event = {
        "version": "2.0",
        "routeKey": "GET /health",
        "rawPath": "/health",
        "headers": {},
        "requestContext": {
            "http": {"method": "GET", "path": "/health", "sourceIp": "127.0.0.1"}
        },
        "isBase64Encoded": False,
    }

    for _ in range(3):
        response = handler(event, None)
        assert response["statusCode"] == 200
