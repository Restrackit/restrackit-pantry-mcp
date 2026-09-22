import time

import httpx

from pantry_mcp.config import Settings


class TokenProvider:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
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
            "username": self._settings.keycloak_username,
            "password": self._settings.keycloak_password,
        }
        async with httpx.AsyncClient() as client:
            response = await client.post(url, data=data)
            response.raise_for_status()
            payload = response.json()

        self._token = payload["access_token"]
        self._expires_at = time.monotonic() + payload["expires_in"] - 10
        return self._token
