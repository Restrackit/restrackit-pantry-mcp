import time

import httpx

from pantry_mcp.config import Settings


class TokenProvider:
    """Logs in as one specific Keycloak account (password grant) and caches its token.

    Takes the account's own username/password explicitly rather than reading
    a single global credential: each tenant authenticates as their own
    Keycloak account, so a routing bug here can never authenticate as a
    different tenant.
    """

    def __init__(self, settings: Settings, username: str, password: str) -> None:
        self._settings = settings
        self._username = username
        self._password = password
        self._token: str | None = None
        self._expires_at: float = 0.0

    async def get_token(self) -> str:
        if self._token is not None and time.monotonic() < self._expires_at:
            return self._token

        url = (
            f"{self._settings.keycloak_url}/realms/{self._settings.keycloak_realm}"
            "/protocol/openid-connect/token"
        )
        data = {
            "grant_type": "password",
            "client_id": self._settings.keycloak_client_id,
            "username": self._username,
            "password": self._password,
        }
        async with httpx.AsyncClient() as client:
            response = await client.post(url, data=data)
            response.raise_for_status()
            payload = response.json()

        self._token = payload["access_token"]
        self._expires_at = time.monotonic() + payload["expires_in"] - 10
        return self._token
