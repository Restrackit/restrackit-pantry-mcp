from unittest.mock import AsyncMock

import pytest

from pantry_mcp.pantry import (
    add_purchase,
    delete_category,
    delete_product,
    get_expiring_items,
    get_pantry_status,
    list_products,
    move_item,
    record_consumption,
)


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


async def test_get_expiring_items_sorts_by_expiry_date_ascending():
    client = AsyncMock()
    client.list_open_batches.return_value = [
        {"product_name": "Latte", "expiry_date": "2026-10-05"},
        {"product_name": "Pasta", "expiry_date": "2027-01-01"},
        {"product_name": "Yogurt", "expiry_date": "2026-09-25"},
    ]

    items = await get_expiring_items(client)

    assert items == [
        {"product_name": "Yogurt", "expiry_date": "2026-09-25"},
        {"product_name": "Latte", "expiry_date": "2026-10-05"},
        {"product_name": "Pasta", "expiry_date": "2027-01-01"},
    ]


@pytest.mark.parametrize("quantity", [0, -1])
async def test_record_consumption_rejects_non_positive_quantity(quantity):
    client = AsyncMock()

    with pytest.raises(ValueError, match="quantity must be at least 1"):
        await record_consumption(client, "Pasta", quantity)

    client.list_open_batches.assert_not_awaited()


async def test_list_products_returns_name_and_category_only():
    client = AsyncMock()
    client.list_products.return_value = [
        {"public_id": "p1", "name": "pasta", "category": "alimentari", "version": 1}
    ]

    result = await list_products(client, "alimentari")

    client.list_products.assert_awaited_once_with("alimentari")
    assert result == [{"name": "pasta", "category": "alimentari"}]


async def test_delete_product_and_category_delegate_to_client():
    client = AsyncMock()

    assert await delete_product(client, "pasta") == {"deleted": "pasta"}
    assert await delete_category(client, "pasta") == {"deleted": "pasta"}

    client.delete_product.assert_awaited_once_with("pasta")
    client.delete_category.assert_awaited_once_with("pasta")


async def test_move_item_moves_oldest_batches_and_ensures_rules():
    client = AsyncMock()
    client.get_storage_method_public_id.return_value = "sm-dest"
    client.list_storage_methods.return_value = [
        {"public_id": "sm-disp", "name": "dispensa"},
        {"public_id": "sm-dest", "name": "congelatore"},
    ]
    client.list_open_batches.return_value = [
        {"public_id": "b1", "version": 1, "product_public_id": "p1", "current_storage_method_public_id": "sm-disp"},
        {"public_id": "b2", "version": 2, "product_public_id": "p1", "current_storage_method_public_id": "sm-disp"},
        {"public_id": "b3", "version": 1, "product_public_id": "p1", "current_storage_method_public_id": "sm-dest"},
    ]

    result = await move_item(client, "Petto di pollo", "congelatore", quantity=2)

    client.ensure_storage_method.assert_awaited_once_with("congelatore")
    client.ensure_storage_rule.assert_awaited_once_with("p1", "sm-dest", "congelatore")
    assert client.move_batch_storage.await_count == 2
    client.move_batch_storage.assert_any_await("b1", version=1, storage_method_public_id="sm-dest")
    client.move_batch_storage.assert_any_await("b2", version=2, storage_method_public_id="sm-dest")
    assert result == {"moved": 2, "missing": 0, "destination": "congelatore"}


async def test_move_item_filters_by_source_storage_method():
    client = AsyncMock()
    client.get_storage_method_public_id.return_value = "sm-freezer"
    client.list_storage_methods.return_value = [
        {"public_id": "sm-fridge", "name": "frigo"},
        {"public_id": "sm-pantry", "name": "dispensa"},
        {"public_id": "sm-freezer", "name": "congelatore"},
    ]
    client.list_open_batches.return_value = [
        {"public_id": "b1", "version": 1, "product_public_id": "p1", "current_storage_method_public_id": "sm-pantry"},
        {"public_id": "b2", "version": 1, "product_public_id": "p1", "current_storage_method_public_id": "sm-fridge"},
    ]

    result = await move_item(
        client, "Pane", "congelatore", quantity=1, source_storage_method="frigo"
    )

    client.move_batch_storage.assert_awaited_once_with("b2", version=1, storage_method_public_id="sm-freezer")
    assert result == {"moved": 1, "missing": 0, "destination": "congelatore"}


async def test_move_item_looks_up_product_if_not_in_batch():
    client = AsyncMock()
    client.get_storage_method_public_id.return_value = "sm-fridge"
    client.list_storage_methods.return_value = [
        {"public_id": "sm-fridge", "name": "frigo"},
    ]
    client.list_open_batches.return_value = [
        {"public_id": "b1", "version": 1, "current_storage_method_public_id": None},
    ]
    client.find_product.return_value = {"public_id": "prod-42", "name": "Latte"}

    result = await move_item(client, "Latte", "frigo", quantity=1)

    client.find_product.assert_awaited_once_with("Latte")
    client.ensure_storage_rule.assert_awaited_once_with("prod-42", "sm-fridge", "frigo")
    client.move_batch_storage.assert_awaited_once_with("b1", version=1, storage_method_public_id="sm-fridge")
    assert result == {"moved": 1, "missing": 0, "destination": "frigo"}


async def test_move_item_reports_shortfall():
    client = AsyncMock()
    client.get_storage_method_public_id.return_value = "sm-dest"
    client.list_storage_methods.return_value = [{"public_id": "sm-dest", "name": "frigo"}]
    client.list_open_batches.return_value = []

    result = await move_item(client, "Uova", "frigo", quantity=2)

    assert result == {"moved": 0, "missing": 2, "destination": "frigo"}
    client.move_batch_storage.assert_not_awaited()


@pytest.mark.parametrize("quantity", [0, -1])
async def test_move_item_rejects_non_positive_quantity(quantity):
    client = AsyncMock()

    with pytest.raises(ValueError, match="quantity must be at least 1"):
        await move_item(client, "Latte", "frigo", quantity)
