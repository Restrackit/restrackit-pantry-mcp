"""Valida i JWT emessi da Keycloak per pantry-mcp-connector.

Il JWKS viene messo in cache in-process con un TTL fisso invece di essere
rifetchato ad ogni richiesta: stesso principio del cache TTL di
KeycloakAuthenticator in restrackit-core, adattato qui senza Redis (pantry-mcp
non ha uno store condiviso tra invocazioni Lambda fredde).
"""

import time

import httpx
from jose import JWTError, jwt

from pantry_mcp.config import Settings

_JWKS_CACHE_TTL_SECONDS = 3600


class JWTValidationError(Exception):
    """Il token utente è mancante, scaduto, mal firmato o ha claim non validi."""


class _JWKSCache:
    """Cache in-process del JWKS con TTL fisso e refresh forzato opzionale."""

    def __init__(self) -> None:
        """Inizializza la cache vuota."""
        self._jwks: dict | None = None
        self._fetched_at: float = 0.0

    async def get(self, jwks_url: str, *, force_refresh: bool = False) -> dict:
        """Ritorna il JWKS, rifetchandolo se scaduto o se `force_refresh` è True."""
        if (
            not force_refresh
            and self._jwks is not None
            and time.monotonic() - self._fetched_at < _JWKS_CACHE_TTL_SECONDS
        ):
            return self._jwks

        async with httpx.AsyncClient() as client:
            response = await client.get(jwks_url)
            response.raise_for_status()
            self._jwks = response.json()
            self._fetched_at = time.monotonic()
            return self._jwks


_cache = _JWKSCache()


async def validate_user_token(settings: Settings, token: str) -> dict:
    """Valida firma/scadenza/audience del token utente e ne ritorna i claim.

    Solleva `JWTValidationError` per qualunque problema (JWKS irraggiungibile,
    firma non valida, token scaduto, audience errata) — il chiamante (il
    middleware) trasforma sempre questo in un 401 uniforme, senza distinguere
    il motivo specifico.
    """
    jwks_url = (
        f"{settings.keycloak_url}/realms/{settings.keycloak_realm}"
        "/protocol/openid-connect/certs"
    )
    issuer = f"{settings.keycloak_url}/realms/{settings.keycloak_realm}"
    try:
        jwks = await _cache.get(jwks_url)
        try:
            payload = jwt.decode(
                token,
                jwks,
                algorithms=["RS256"],
                audience=settings.keycloak_connector_client_id,
                issuer=issuer,
            )
        except JWTError:
            # La chiave potrebbe essere ruotata: un solo retry con JWKS forzatamente
            # fresco, stesso pattern di _decode_token_with_retry in restrackit-core.
            jwks = await _cache.get(jwks_url, force_refresh=True)
            payload = jwt.decode(
                token,
                jwks,
                algorithms=["RS256"],
                audience=settings.keycloak_connector_client_id,
                issuer=issuer,
            )
    except (JWTError, httpx.HTTPError) as error:
        raise JWTValidationError(str(error)) from error

    # python-jose skips the audience check entirely when `aud` is absent from
    # the token instead of rejecting it (jose/jwt.py `_validate_aud`), so a
    # realm-signed token with no `aud` claim at all would otherwise pass.
    if "aud" not in payload:
        raise JWTValidationError("Missing aud claim")
    return payload
