"""Tenant registry: resolves a friend's bearer token to their restrackit-core store.

DynamoDB is the source of truth so a new friend can be onboarded with a
single ``put-item`` (see ``scripts/add_tenant.py``) and no redeploy. Lookup
failures (unknown token, unreachable table) both resolve to ``None`` —
the caller (the auth middleware) turns that into a uniform 401, so a
DynamoDB outage can never be mistaken for "let everyone in".
"""

import hashlib
from asyncio import to_thread

import boto3
from botocore.exceptions import ClientError
from pydantic import BaseModel


class Tenant(BaseModel):
    """A single friend's identity: which restrackit-core store they own."""

    store_id: int
    name: str


def hash_token(token: str) -> str:
    """Hash a bearer token for storage/lookup; the plaintext is never persisted."""
    return hashlib.sha256(token.encode()).hexdigest()


class TenantStore:
    """Looks up a `Tenant` by bearer token in the `PantryMcpTenants` DynamoDB table."""

    def __init__(self, table_name: str) -> None:
        self._table_name = table_name
        self._client = boto3.client("dynamodb")

    async def resolve(self, token: str) -> Tenant | None:
        """Return the tenant for `token`, or `None` if unknown or the table errors."""
        try:
            response = await to_thread(
                self._client.get_item,
                TableName=self._table_name,
                Key={"token_hash": {"S": hash_token(token)}},
            )
        except ClientError:
            return None

        item = response.get("Item")
        if item is None:
            return None
        return Tenant(store_id=int(item["store_id"]["N"]), name=item["name"]["S"])
