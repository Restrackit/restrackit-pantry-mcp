from unittest.mock import AsyncMock

from pantry_mcp.pantry import add_purchase, get_pantry_status, record_consumption


async def test_add_purchase_creates_one_batch_per_unit():
    client = AsyncMock()
    client.ensure_product.return_value = "prod-1"
    client.get_storage_method_public_id.return_value = "storage-1"

    result = await add_purchase(
        client,
        [
            {
                "product_name": "Pasta",
                "quantity": 2,
                "category": "alimentari",
                "expiry_date": "2027-01-01",
                "storage_method": "dispensa",
            }
        ],
    )

    client.ensure_category.assert_awaited_once_with("alimentari")
    client.ensure_storage_method.assert_awaited_once_with("dispensa")
    client.ensure_product.assert_awaited_once_with("Pasta", "alimentari")
    client.ensure_storage_rule.assert_awaited_once_with("prod-1", "storage-1", "dispensa")
    assert client.confirm_batch.await_count == 2
    assert result["items_created"] == 2


async def test_get_pantry_status_aggregates_open_batches_by_product():
    client = AsyncMock()
    client.list_open_batches.side_effect = lambda product_name=None: [  # type: ignore[misc]
        {"product_name": "Pasta"},
        {"product_name": "Pasta"},
        {"product_name": "Latte"},
    ]

    status = await get_pantry_status(client)

    assert status == {"Pasta": 2, "Latte": 1}


async def test_record_consumption_closes_oldest_batches_first():
    client = AsyncMock()
    client.list_open_batches.return_value = [
        {"public_id": "b1", "version": 1},
        {"public_id": "b2", "version": 1},
        {"public_id": "b3", "version": 1},
    ]

    result = await record_consumption(client, "Pasta", 2)

    assert client.complete_batch.await_count == 2
    client.complete_batch.assert_any_await("b1", version=1, reason="other")
    client.complete_batch.assert_any_await("b2", version=1, reason="other")
    assert result == {"closed": 2, "missing": 0}


async def test_record_consumption_reports_shortfall():
    client = AsyncMock()
    client.list_open_batches.return_value = [{"public_id": "b1", "version": 1}]

    result = await record_consumption(client, "Pasta", 3)

    assert client.complete_batch.await_count == 1
    assert result == {"closed": 1, "missing": 2}
