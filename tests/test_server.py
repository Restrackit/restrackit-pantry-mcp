import json

import boto3
import pytest
import respx
from httpx import Response
from moto import mock_aws
from starlette.testclient import TestClient

from pantry_mcp import server
from pantry_mcp.credentials import secret_name
from pantry_mcp.tenants import hash_token

TABLE_NAME = "PantryMcpTenants"


@pytest.fixture(autouse=True)
def _settings_env(monkeypatch):
    monkeypatch.setenv("KEYCLOAK_URL", "https://kc.example.com")
    monkeypatch.setenv("KEYCLOAK_REALM", "restrackit")
    monkeypatch.setenv("KEYCLOAK_CLIENT_ID", "restrackit-core")
    monkeypatch.setenv("RESTRACKIT_BASE_URL", "https://api.example.com/v1")
    monkeypatch.setenv("TENANTS_TABLE_NAME", TABLE_NAME)
    monkeypatch.setenv("AWS_DEFAULT_REGION", "eu-west-1")


@pytest.fixture(autouse=True)
def _reset_token_providers():
    """`server._token_providers` is a module-level cache — clear it so a
    TokenProvider (and its cached token) from one test never leaks into the
    next test's differently-mocked AWS/Keycloak backends."""
    server._token_providers.clear()
    yield
    server._token_providers.clear()


@pytest.fixture(autouse=True)
def _tenants_table():
    with mock_aws():
        client = boto3.client("dynamodb", region_name="eu-west-1")
        client.create_table(
            TableName=TABLE_NAME,
            KeySchema=[{"AttributeName": "token_hash", "KeyType": "HASH"}],
            AttributeDefinitions=[
                {"AttributeName": "token_hash", "AttributeType": "S"}
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        client.put_item(
            TableName=TABLE_NAME,
            Item={
                "token_hash": {"S": hash_token("expected-token")},
                "store_id": {"N": "1"},
                "name": {"S": "Luca"},
            },
        )
        client.put_item(
            TableName=TABLE_NAME,
            Item={
                "token_hash": {"S": hash_token("friend-token")},
                "store_id": {"N": "2"},
                "name": {"S": "Marco"},
            },
        )

        secretsmanager = boto3.client("secretsmanager", region_name="eu-west-1")
        for store_id, username in ((1, "luca-user"), (2, "marco-user")):
            secretsmanager.create_secret(
                Name=secret_name(store_id),
                SecretString=json.dumps({"username": username, "password": "irrelevant"}),
            )

        yield client


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


def test_mcp_endpoint_rejects_unknown_bearer_token():
    client = TestClient(server.app)

    response = client.post("/mcp", json={}, headers={"Authorization": "Bearer wrong"})

    assert response.status_code == 401


def test_mcp_handshake_lists_all_tools():
    headers = {
        "Authorization": "Bearer expected-token",
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


def _call_get_pantry_status(client, headers):
    with client:
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
        return client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "get_pantry_status", "arguments": {}},
            },
            headers=headers,
        )


@respx.mock
def test_different_tokens_route_to_different_stores():
    respx.get("https://api.example.com/v1/inventory/list").mock(
        return_value=Response(
            200, json={"status": "ok", "count": 0, "items": [], "next_cursor": None}
        )
    )
    respx.post(
        "https://kc.example.com/realms/restrackit/protocol/openid-connect/token"
    ).mock(
        return_value=Response(200, json={"access_token": "fake-jwt", "expires_in": 300})
    )

    _call_get_pantry_status(
        TestClient(server.create_app()),
        {
            "Authorization": "Bearer expected-token",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
    )
    _call_get_pantry_status(
        TestClient(server.create_app()),
        {
            "Authorization": "Bearer friend-token",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
    )

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
