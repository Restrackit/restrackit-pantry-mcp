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


async def get_pantry_status(
    client: RestrackitClient, product_name: str | None = None
) -> dict[str, int]:
    """Return a count of open batches per product name."""
    batches = await client.list_open_batches(product_name)
    counts = Counter(batch["product_name"] for batch in batches)
    return dict(counts)


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
