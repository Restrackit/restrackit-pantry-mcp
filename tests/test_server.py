import pytest
from starlette.testclient import TestClient

from pantry_mcp import server


@pytest.fixture(autouse=True)
def _settings_env(monkeypatch):
    monkeypatch.setenv("KEYCLOAK_URL", "https://kc.example.com")
    monkeypatch.setenv("KEYCLOAK_REALM", "restrackit")
    monkeypatch.setenv("KEYCLOAK_CLIENT_ID", "restrackit-core")
    monkeypatch.setenv("KEYCLOAK_USERNAME", "restrackit-pantry-mcp")
    monkeypatch.setenv("KEYCLOAK_PASSWORD", "secret")
    monkeypatch.setenv("RESTRACKIT_BASE_URL", "https://api.example.com/v1")
    monkeypatch.setenv("RESTRACKIT_STORE_ID", "1")
    monkeypatch.setenv("MCP_AUTH_TOKEN", "expected-token")


def test_health_check_requires_no_auth():
    client = TestClient(server.app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_mcp_endpoint_allows_cors_preflight_without_auth():
    """Connector clients probe with an unauthenticated OPTIONS preflight first."""
    client = TestClient(server.app)

    response = client.options(
        "/mcp",
        headers={"Origin": "https://claude.ai", "Access-Control-Request-Method": "POST"},
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "*"


def test_mcp_endpoint_rejects_missing_bearer_token():
    client = TestClient(server.app)

    response = client.post("/mcp", json={})

    assert response.status_code == 401


def test_mcp_endpoint_rejects_wrong_bearer_token():
    client = TestClient(server.app)

    response = client.post("/mcp", json={}, headers={"Authorization": "Bearer wrong"})

    assert response.status_code == 401


def test_mcp_handshake_lists_all_tools():
    headers = {
        "Authorization": "Bearer expected-token",
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }

    # Build a fresh app instead of reusing the module-level `server.app`: its
    # StreamableHTTPSessionManager can only run its lifespan once per
    # instance, and `TestClient(...)` as a context manager triggers that
    # lifespan — reusing `server.app` here would break the lambda handler
    # test, which also starts it (via Mangum).
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
        assert init_response.json()["result"]["serverInfo"]["name"] == "restrackit-pantry-mcp"

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
