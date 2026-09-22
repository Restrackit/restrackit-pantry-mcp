from typing import Any, Protocol

import httpx

from pantry_mcp.config import Settings


class _TokenSource(Protocol):
    async def get_token(self) -> str: ...


class RestrackitApiError(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.status_code = status_code
        self.code = code
        self.message = message


def is_already_exists(error: RestrackitApiError) -> bool:
    return error.code == "ERR_BUS_004"


class RestrackitClient:
    def __init__(self, settings: Settings, token_provider: _TokenSource) -> None:
        self._settings = settings
        self._token_provider = token_provider

    async def request(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        token = await self._token_provider.get_token()
        request_headers = {
            "Authorization": f"Bearer {token}",
            "X-Target-Store": str(self._settings.restrackit_store_id),
            **(headers or {}),
        }
        url = f"{self._settings.restrackit_base_url}{path}"

        async with httpx.AsyncClient() as client:
            response = await client.request(
                method, url, json=json, params=params, headers=request_headers
            )

        if response.status_code >= 400:
            body = response.json()
            error = body.get("error", {})
            raise RestrackitApiError(
                response.status_code,
                error.get("code", "UNKNOWN"),
                error.get("message", response.text),
            )
        return response

    async def ensure_category(self, name: str) -> None:
        response = await self.request("GET", "/categories")
        existing = {item["name"].lower() for item in response.json()}
        if name.lower() in existing:
            return
        try:
            await self.request("POST", "/categories", json={"name": name})
        except RestrackitApiError as error:
            if not is_already_exists(error):
                raise

    async def ensure_storage_method(self, name: str) -> None:
        response = await self.request("GET", "/storage-methods")
        existing = {item["name"].lower() for item in response.json()}
        if name.lower() in existing:
            return
        try:
            await self.request("POST", "/storage-methods", json={"name": name})
        except RestrackitApiError as error:
            if not is_already_exists(error):
                raise
