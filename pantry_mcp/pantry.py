"""Domain logic layered on top of ``RestrackitClient``.

Pure orchestration: no HTTP calls happen here directly, only calls into the
injected client.
"""

import hashlib
from collections import Counter
from datetime import UTC, datetime
from typing import Any, TypedDict

from pantry_mcp.restrackit_client import RestrackitClient


class PurchaseItem(TypedDict):
    """A single purchased product to register in the pantry."""

    product_name: str
    quantity: int
    category: str
    expiry_date: str
    storage_method: str


def _generate_lot_code(product_name: str, unit_index: int) -> str:
    """Build a unique-per-unit, unique-per-call lot code.

    Includes a timestamp (not just a date) because this value doubles as the
    ``Idempotency-Key`` sent to ``confirm_batch``, and restrackit-core dedupes
    idempotency keys with a 24-hour TTL — a second purchase of the same
    product on the same day must not collide with the first.
    """
    digest = hashlib.sha1(product_name.encode()).hexdigest()[:8]
    return f"{datetime.now(UTC):%Y%m%dT%H%M%S}-{digest}-{unit_index}"


async def add_purchase(client: RestrackitClient, items: list[PurchaseItem]) -> dict[str, int]:
    """Register a purchase, creating one batch per unit of quantity."""
    total_created = 0
    for item in items:
        await client.ensure_category(item["category"])
        await client.ensure_storage_method(item["storage_method"])

        product_public_id = await client.ensure_product(item["product_name"], item["category"])
        storage_public_id = await client.get_storage_method_public_id(item["storage_method"])
        await client.ensure_storage_rule(
            product_public_id, storage_public_id, item["storage_method"]
        )

        for unit_index in range(item["quantity"]):
            lot_code = _generate_lot_code(item["product_name"], unit_index)
            await client.confirm_batch(
                item["product_name"], storage_public_id, item["expiry_date"], lot_code
            )
            total_created += 1

    return {"items_created": total_created}


async def list_products(
    client: RestrackitClient, category: str | None = None
) -> list[dict[str, str]]:
    """Return the product masters (name + category) already registered in the store."""
    products = await client.list_products(category)
    return [{"name": p["name"], "category": p["category"]} for p in products]


async def delete_product(client: RestrackitClient, product_name: str) -> dict[str, str]:
    """Delete a product master by name."""
    await client.delete_product(product_name)
    return {"deleted": product_name}


async def delete_category(client: RestrackitClient, category_name: str) -> dict[str, str]:
    """Delete a category by name."""
    await client.delete_category(category_name)
    return {"deleted": category_name}


async def get_pantry_status(
    client: RestrackitClient, product_name: str | None = None
) -> dict[str, int]:
    """Return a count of open batches per product name."""
    batches = await client.list_open_batches(product_name)
    counts = Counter(batch["product_name"] for batch in batches)
    return dict(counts)


async def get_expiring_items(client: RestrackitClient) -> list[dict[str, Any]]:
    """Return open batches sorted by expiry date, soonest first."""
    batches = await client.list_open_batches()
    items = [
        {"product_name": batch["product_name"], "expiry_date": batch["expiry_date"]}
        for batch in batches
    ]
    items.sort(key=lambda item: item["expiry_date"])
    return items


async def record_consumption(
    client: RestrackitClient, product_name: str, quantity: int
) -> dict[str, Any]:
    """Close the oldest open batches for a product to record consumption."""
    if quantity < 1:
        raise ValueError("quantity must be at least 1")

    open_batches = await client.list_open_batches(product_name)
    to_close = open_batches[:quantity]

    for batch in to_close:
        await client.complete_batch(batch["public_id"], version=batch["version"], reason="other")

    missing = quantity - len(to_close)
    return {"closed": len(to_close), "missing": max(missing, 0)}


async def move_item(
    client: RestrackitClient,
    product_name: str,
    destination_storage_method: str,
    quantity: int = 1,
    source_storage_method: str | None = None,
) -> dict[str, Any]:
    """Move open batches of a product to a new storage method (oldest first).

    Optionally filters by `source_storage_method`. If not specified, selects
    batches that are not already in the destination storage method.
    """
    if quantity < 1:
        raise ValueError("quantity must be at least 1")

    dest_norm = destination_storage_method.strip().lower()
    await client.ensure_storage_method(dest_norm)
    dest_storage_id = await client.get_storage_method_public_id(dest_norm)

    storage_methods = await client.list_storage_methods()
    id_to_name = {sm["public_id"]: sm["name"].lower() for sm in storage_methods}

    source_norm = source_storage_method.strip().lower() if source_storage_method else None

    open_batches = await client.list_open_batches(product_name)

    candidates: list[dict[str, Any]] = []
    for batch in open_batches:
        current_sm_id = batch.get("current_storage_method_public_id")
        current_name = id_to_name.get(current_sm_id) if current_sm_id else None

        if source_norm is not None:
            if current_name == source_norm:
                candidates.append(batch)
        else:
            if current_name != dest_norm:
                candidates.append(batch)

    to_move = candidates[:quantity]

    if to_move:
        product_public_id = to_move[0].get("product_public_id")
        if not product_public_id:
            product = await client.find_product(product_name)
            if product is not None:
                product_public_id = product["public_id"]
        if product_public_id:
            await client.ensure_storage_rule(product_public_id, dest_storage_id, dest_norm)

        for batch in to_move:
            await client.move_batch_storage(
                batch["public_id"],
                version=batch.get("version", 1),
                storage_method_public_id=dest_storage_id,
            )

    missing = quantity - len(to_move)
    return {
        "moved": len(to_move),
        "missing": max(missing, 0),
        "destination": dest_norm,
    }
