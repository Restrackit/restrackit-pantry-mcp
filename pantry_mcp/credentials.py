"""Per-tenant Keycloak credentials, stored in AWS Secrets Manager.

Each tenant authenticates as their own Keycloak account (created via
restrackit-core's ``/onboarding/stores`` endpoint), not a shared one — a
routing bug in this server can misdirect a request to the wrong store, but
it can never authenticate as a different tenant's Keycloak account, unlike
a single shared account addressing many stores via ``X-Target-Store``.
"""

from asyncio import to_thread
from functools import lru_cache
from json import loads as json_loads

import boto3
from pydantic import BaseModel


def secret_name(store_id: int) -> str:
    """Secrets Manager secret name for a tenant's Keycloak credentials."""
    return f"pantry-mcp/tenants/{store_id}"


class TenantCredentials(BaseModel):
    """A tenant's own Keycloak username/password."""

    username: str
    password: str


class CredentialStore:
    """Fetches a tenant's Keycloak credentials from Secrets Manager."""

    def __init__(self) -> None:
        self._client = boto3.client("secretsmanager")

    async def get(self, store_id: int) -> TenantCredentials:
        """Return the tenant's credentials, or raise if the secret is missing/unreachable.

        Unlike ``TenantStore.resolve``, this runs *after* the caller has
        already been authorized — a missing or unreadable secret here is an
        operational misconfiguration, not an authorization decision, so it
        propagates as an error instead of being swallowed into a 401.
        """
        response = await to_thread(self._client.get_secret_value, SecretId=secret_name(store_id))
        payload = json_loads(response["SecretString"])
        return TenantCredentials(username=payload["username"], password=payload["password"])


@lru_cache
def get_credential_store() -> CredentialStore:
    return CredentialStore()
