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


STORAGE_METHOD_DEFAULT_DURATION_DAYS = {
    "dispensa": 180,
    "frigo": 7,
    "congelatore": 180,
}


class RestrackitClient:
    def __init__(self, settings: Settings, token_provider: _TokenSource, store_id: int) -> None:
        self._settings = settings
        self._token_provider = token_provider
        self._store_id = store_id

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
            "X-Target-Store": str(self._store_id),
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

    async def get_storage_method_public_id(self, name: str) -> str:
        response = await self.request("GET", "/storage-methods")
        for item in response.json():
            if item["name"].lower() == name.lower():
                return item["public_id"]
        raise LookupError(f"Storage method '{name}' not found")

    async def ensure_product(self, name: str, category: str) -> str:
        await self.request(
            "POST",
            "/products/bulk-load",
            json=[{"name": name, "category": category, "allergens": []}],
        )
        response = await self.request("GET", "/products/list", params={"category": category})
        for item in response.json()["items"]:
            if item["name"].lower() == name.lower():
                return item["public_id"]
        raise LookupError(f"Product '{name}' not found after bulk-load")

    async def ensure_storage_rule(
        self, product_public_id: str, storage_method_public_id: str, storage_method_name: str
    ) -> None:
        duration_days = STORAGE_METHOD_DEFAULT_DURATION_DAYS.get(
            storage_method_name.lower(), 180
        )
        try:
            await self.request(
                "POST",
                f"/products/{product_public_id}/storage-rules",
                json={
                    "storage_method_public_id": storage_method_public_id,
                    "duration_days": duration_days,
                    "duration_hours": 0,
                },
            )
        except RestrackitApiError as error:
            if not is_already_exists(error):
                raise

    async def confirm_batch(
        self, product_name: str, storage_method_public_id: str, expiry_date: str, lot_code: str
    ) -> dict[str, Any]:
        response = await self.request(
            "POST",
            "/inventory/confirm",
            json={
                "product_name": product_name,
                "lot_code": lot_code,
                "expiry_date": expiry_date,
                "confidence": 1.0,
                "storage_method_public_id": storage_method_public_id,
            },
            headers={"Idempotency-Key": lot_code},
        )
        return response.json()

    async def list_open_batches(self, product_name: str | None = None) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            params: dict[str, Any] = {
                "is_empty": "false",
                "sort": "id",
                "order": "asc",
            }
            if product_name is not None:
                params["product_name"] = product_name
            if cursor is not None:
                params["cursor"] = cursor
            response = await self.request("GET", "/inventory/list", params=params)
            payload = response.json()
            items.extend(payload["items"])
            cursor = payload["next_cursor"]
            if cursor is None:
                return items

    async def complete_batch(
        self, batch_id: str, version: int, reason: str = "other"
    ) -> dict[str, Any]:
        response = await self.request(
            "POST",
            f"/inventory/batch/{batch_id}/complete",
            json={"reason": reason, "version": version},
        )
        return response.json()
