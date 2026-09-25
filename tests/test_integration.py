"""End-to-end integration test against a real restrackit-core + Keycloak instance.

Skipped by default: only runs when RUN_INTEGRATION_TESTS=1 is set and a valid
.env points at a real test store and tenant user (see .env.example). No
network calls happen in the default test run.

In production, pantry-mcp never authenticates the user itself: Claude drives
the OAuth "Sign in now" browser flow against Keycloak and hands the resulting
`pantry-mcp-connector` access token to pantry-mcp, which exchanges it
server-side (`TokenExchanger`, RFC 8693) for one scoped to
`restrackit-backend`. This test has no browser to drive, so it stands in for
that first step with a direct Resource Owner Password Credentials grant
against `pantry-mcp-connector` — which requires **Direct Access Grants** to
be temporarily enabled for that client in the Keycloak realm. Nothing in
pantry-mcp's own runtime code path uses this grant; it exists solely so this
test can obtain a "real" user token to feed into the real `TokenExchanger`
and exercise the full server-side exchange + REST call path.
"""

import os

import httpx
import pytest

from pantry_mcp.auth import TokenExchanger
from pantry_mcp.config import get_settings
from pantry_mcp.pantry import add_purchase, get_pantry_status, record_consumption
from pantry_mcp.restrackit_client import RestrackitClient

pytestmark = pytest.mark.integration

requires_live_store = pytest.mark.skipif(
    os.getenv("RUN_INTEGRATION_TESTS") != "1",
    reason=(
        "requires RUN_INTEGRATION_TESTS=1, a real restrackit-core + Keycloak "
        "instance, and Direct Access Grants enabled on pantry-mcp-connector"
    ),
)


class _ExchangedTokenSource:
    """Adapts TokenExchanger to RestrackitClient's `_TokenSource` protocol."""

    def __init__(self, exchanger: TokenExchanger, user_token: str) -> None:
        """Store the exchanger and the raw user token to exchange on each call."""
        self._exchanger = exchanger
        self._user_token = user_token

    async def get_token(self) -> str:
        """Return a restrackit-backend-scoped token for the stored user token."""
        return await self._exchanger.exchange(self._user_token)


async def _fetch_real_user_token(settings) -> str:
    """Obtain a real `pantry-mcp-connector` user access token via password grant.

    Stands in for the browser OAuth login Claude normally performs; see the
    module docstring for why this requires Direct Access Grants.
    """
    url = f"{settings.keycloak_url}/realms/{settings.keycloak_realm}/protocol/openid-connect/token"
    async with httpx.AsyncClient() as client:
        response = await client.post(
            url,
            data={
                "grant_type": "password",
                "client_id": settings.keycloak_connector_client_id,
                "username": os.environ["RESTRACKIT_TEST_KEYCLOAK_USERNAME"],
                "password": os.environ["RESTRACKIT_TEST_KEYCLOAK_PASSWORD"],
            },
        )
        response.raise_for_status()
        return response.json()["access_token"]


@requires_live_store
async def test_full_purchase_status_consumption_cycle():
    """Exercise add_purchase -> get_pantry_status -> record_consumption end to end."""
    settings = get_settings()
    store_id = int(os.environ["RESTRACKIT_TEST_STORE_ID"])
    user_token = await _fetch_real_user_token(settings)
    token_source = _ExchangedTokenSource(TokenExchanger(settings), user_token)
    client = RestrackitClient(settings, token_source, store_id=store_id)
    product_name = "Test Pasta Integrazione"

    await add_purchase(
        client,
        [
            {
                "product_name": product_name,
                "quantity": 3,
                "category": "alimentari",
                "expiry_date": "2027-01-01",
                "storage_method": "dispensa",
            }
        ],
    )

    status = await get_pantry_status(client, product_name)
    assert status[product_name] == 3

    result = await record_consumption(client, product_name, 2)
    assert result == {"closed": 2, "missing": 0}

    status_after = await get_pantry_status(client, product_name)
    assert status_after[product_name] == 1
