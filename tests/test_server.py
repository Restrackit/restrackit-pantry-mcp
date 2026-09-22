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


def test_mcp_endpoint_rejects_missing_bearer_token():
    client = TestClient(server.app)

    response = client.post("/mcp", json={})

    assert response.status_code == 401


def test_mcp_endpoint_rejects_wrong_bearer_token():
    client = TestClient(server.app)

    response = client.post("/mcp", json={}, headers={"Authorization": "Bearer wrong"})

    assert response.status_code == 401


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
