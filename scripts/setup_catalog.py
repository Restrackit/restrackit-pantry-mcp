"""One-time script to pre-populate the catalog for a new store.

Creates the initial categories and the fixed set of storage methods used by
this project, via the existing ``RestrackitClient``. Idempotent: safe to
re-run, since it reuses ``ensure_category``/``ensure_storage_method``.

Requires a store already created on restrackit-core and a fully configured
``.env`` (see ``.env.example``).
"""

import asyncio

from pantry_mcp.auth import TokenProvider
from pantry_mcp.config import get_settings
from pantry_mcp.restrackit_client import RestrackitClient

INITIAL_CATEGORIES = ["alimentari", "pulizia", "igiene casa"]
STORAGE_METHODS = ["dispensa", "frigo", "congelatore"]


async def main() -> None:
    """Create the starter categories and storage methods, printing progress."""
    settings = get_settings()
    client = RestrackitClient(settings, TokenProvider(settings))

    for category in INITIAL_CATEGORIES:
        await client.ensure_category(category)
        print(f"category ready: {category}")

    for storage_method in STORAGE_METHODS:
        await client.ensure_storage_method(storage_method)
        print(f"storage method ready: {storage_method}")


if __name__ == "__main__":
    asyncio.run(main())
