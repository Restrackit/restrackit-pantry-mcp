"""End-to-end integration test against a real restrackit-core instance.

Skipped by default: only runs when RUN_INTEGRATION_TESTS=1 is set and a
valid .env points at a real test store. No network calls happen in the
default test run.
"""

import os

import pytest

from pantry_mcp.auth import TokenProvider
from pantry_mcp.config import get_settings
from pantry_mcp.pantry import add_purchase, get_pantry_status, record_consumption
from pantry_mcp.restrackit_client import RestrackitClient

pytestmark = pytest.mark.integration

requires_live_store = pytest.mark.skipif(
    os.getenv("RUN_INTEGRATION_TESTS") != "1",
    reason="requires RUN_INTEGRATION_TESTS=1 and a real restrackit-core instance",
)


@requires_live_store
async def test_full_purchase_status_consumption_cycle():
    """Exercise add_purchase -> get_pantry_status -> record_consumption end to end."""
    settings = get_settings()
    client = RestrackitClient(settings, TokenProvider(settings))
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
