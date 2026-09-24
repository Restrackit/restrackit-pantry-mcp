"""Scambia il token utente (aud=pantry-mcp-connector) per uno aud=restrackit-backend.

RFC 8693 Standard Token Exchange: pantry-mcp non autentica mai l'utente (niente
grant password, niente credenziali di tenant) — riceve il token già emesso da
Keycloak per il login OAuth di Claude e lo scambia lato server usando le
proprie credenziali (pantry-mcp-token-exchange), non quelle dell'utente.
"""

import time

import httpx

from pantry_mcp.config import Settings

_CACHE_EXPIRY_MARGIN_SECONDS = 10


class TokenExchanger:
    """Scambia un token utente per un token scoped a restrackit-backend.

    La cache è per singolo token utente in ingresso, non per tenant/store: un
    token utente scade e viene rinnovato dal client (Claude) indipendentemente
    da pantry-mcp, quindi non esiste un provider "di lunga vita" per store da
    tenere in un dict condiviso come nel vecchio TokenProvider.

    Due chiamate concorrenti con lo stesso token utente possono entrambe
    trovare la cache vuota e fare due scambi verso Keycloak in parallelo:
    innocuo (entrambi i risultati sono validi, uno viene solo scartato
    nell'ultima scrittura), stesso principio già accettato nel vecchio
    `_token_providers` di server.py.
    """

    def __init__(self, settings: Settings) -> None:
        """Store settings; no network I/O happens until `exchange` is called."""
        self._settings = settings
        self._cache: dict[str, tuple[str, float]] = {}

    async def exchange(self, user_token: str) -> str:
        """Exchange a user access token for one scoped to restrackit-backend.

        Uses a per-user-token cache to avoid re-exchanging on every call; the
        exchanged token and the client secret used to obtain it are never
        logged or included in raised exceptions.
        """
        cached = self._cache.get(user_token)
        if cached is not None:
            exchanged_token, expires_at = cached
            if time.monotonic() < expires_at:
                return exchanged_token

        url = (
            f"{self._settings.keycloak_url}/realms/{self._settings.keycloak_realm}"
            "/protocol/openid-connect/token"
        )
        data = {
            "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
            "client_id": self._settings.keycloak_exchange_client_id,
            "client_secret": self._settings.keycloak_exchange_client_secret,
            "subject_token": user_token,
            "subject_token_type": "urn:ietf:params:oauth:token-type:access_token",
            "audience": self._settings.restrackit_backend_client_id,
        }
        async with httpx.AsyncClient() as client:
            response = await client.post(url, data=data)
            response.raise_for_status()
            payload = response.json()

        exchanged_token = payload["access_token"]
        expires_at = (
            time.monotonic() + payload["expires_in"] - _CACHE_EXPIRY_MARGIN_SECONDS
        )
        self._cache[user_token] = (exchanged_token, expires_at)
        return exchanged_token
