"""MCP server exposing the pantry tools over streamable HTTP, bearer-protected.

Uses ``mcp`` 2.x, where the v1 ``FastMCP`` class was renamed ``MCPServer``
(module ``mcp.server.mcpserver``); the ``.tool()`` decorator and
``.streamable_http_app()`` method keep the same signature as v1, so only the
import needs adapting.
"""

from contextvars import ContextVar
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from pantry_mcp import pantry
from pantry_mcp.auth import TokenExchanger
from pantry_mcp.config import get_settings
from pantry_mcp.jwks import JWTValidationError, validate_user_token
from pantry_mcp.restrackit_client import RestrackitClient

mcp = MCPServer("restrackit-pantry-mcp")

_current_user_token: ContextVar[str] = ContextVar("current_user_token")
_current_store_id: ContextVar[int] = ContextVar("current_store_id")

# Un solo TokenExchanger per processo: è stateless verso Keycloak (nessuna
# credenziale di tenant), la sua cache interna è già chiavata per user_token
# (Task 4), quindi condividerlo tra richieste è sicuro e riusa la cache.
# Costruito lazy (non al momento dell'import) perché Settings richiede env var
# che nei test vengono impostate da una fixture per-test, dopo che il modulo
# è già stato importato una volta dal collector di pytest.
_exchanger: TokenExchanger | None = None


def _get_exchanger() -> TokenExchanger:
    """Return the process-wide TokenExchanger, creating it on first use."""
    global _exchanger
    if _exchanger is None:
        _exchanger = TokenExchanger(get_settings())
    return _exchanger


class _TokenExchangeSource:
    """Adatta TokenExchanger.exchange al protocollo `_TokenSource` di RestrackitClient."""

    def __init__(self, exchanger: TokenExchanger, user_token: str) -> None:
        """Store the shared exchanger and the current request's user token."""
        self._exchanger = exchanger
        self._user_token = user_token

    async def get_token(self) -> str:
        """Return a restrackit-backend-scoped token for the current user token."""
        return await self._exchanger.exchange(self._user_token)


async def _get_client() -> RestrackitClient:
    """Build a RestrackitClient scoped to the current request's store and user token."""
    settings = get_settings()
    store_id = _current_store_id.get()
    user_token = _current_user_token.get()
    token_source = _TokenExchangeSource(_get_exchanger(), user_token)
    return RestrackitClient(settings, token_source, store_id=store_id)


@mcp.tool()
async def add_purchase(items: list[pantry.PurchaseItem]) -> dict[str, int]:
    """Record a purchase: creates products/categories/storage methods as needed, one batch per unit.

    Each item's ``storage_method`` should be one of ``"dispensa"`` (pantry),
    ``"frigo"`` (fridge), or ``"congelatore"`` (freezer) — these are the only
    values with a tuned default shelf life. Other values are accepted but fall
    back to a generic long shelf life, which is wrong for anything that
    actually needs refrigeration. ``expiry_date`` must be in ``YYYY-MM-DD``
    format.
    """
    return await pantry.add_purchase(await _get_client(), items)


@mcp.tool()
async def get_pantry_status(product_name: str | None = None) -> dict[str, int]:
    """Return the available quantity per product (all products, or one if specified)."""
    return await pantry.get_pantry_status(await _get_client(), product_name)


@mcp.tool()
async def record_consumption(product_name: str, quantity: int) -> dict[str, Any]:
    """Close `quantity` open units of a product (oldest first)."""
    return await pantry.record_consumption(await _get_client(), product_name, quantity)


@mcp.tool()
async def get_expiring_items() -> list[dict[str, Any]]:
    """Return open batches sorted by expiry date, soonest first."""
    return await pantry.get_expiring_items(await _get_client())


def _extract_store_id(payload: dict) -> int:
    """Estrae store_id dal claim del token; solleva se mancante o non numerico.

    Il claim è multivalued nello schema esistente (store_id_mapper in
    restrackit-core, vedi provision_keycloak_realm.sh) — pantry-mcp-connector
    ne assegna sempre uno solo per utente, quindi prende il primo.
    """
    claim = payload.get("store_id")
    if not claim:
        raise JWTValidationError("Missing store_id claim")
    try:
        return int(claim[0] if isinstance(claim, list) else claim)
    except (TypeError, ValueError) as error:
        raise JWTValidationError("Non-numeric store_id claim") from error


_PROTECTED_RESOURCE_PATH = "/.well-known/oauth-protected-resource"


def _unauthorized(settings) -> JSONResponse:
    """Build the uniform 401, with the RFC 9728 discovery hint (RFC 6750 s3)."""
    resource_metadata_url = f"{settings.mcp_public_base_url}{_PROTECTED_RESOURCE_PATH}"
    return JSONResponse(
        {"error": "unauthorized"},
        status_code=401,
        headers={"WWW-Authenticate": f'Bearer resource_metadata="{resource_metadata_url}"'},
    )


class _BearerAuthMiddleware(BaseHTTPMiddleware):
    """Valida il JWT utente di ogni richiesta, o la rifiuta.

    Un header mancante, un JWT invalido/scaduto/con audience errata e un
    claim store_id mancante risultano tutti nello stesso 401 — il chiamante
    non deve poter distinguere quale caso si è verificato.
    """

    async def dispatch(self, request: Request, call_next):
        """Reject requests with no bearer token or one that fails JWT validation."""
        if (
            request.url.path in ("/health", _PROTECTED_RESOURCE_PATH)
            or request.method == "OPTIONS"
        ):
            return await call_next(request)

        settings = get_settings()
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return _unauthorized(settings)
        token = auth_header.removeprefix("Bearer ")

        try:
            payload = await validate_user_token(settings, token)
            store_id = _extract_store_id(payload)
        except JWTValidationError:
            return _unauthorized(settings)

        token_reset = _current_user_token.set(token)
        store_reset = _current_store_id.set(store_id)
        try:
            return await call_next(request)
        finally:
            _current_user_token.reset(token_reset)
            _current_store_id.reset(store_reset)


async def health(request: Request) -> JSONResponse:
    """Liveness check, reachable without authentication."""
    return JSONResponse({"status": "ok"})


async def oauth_protected_resource(request: Request) -> JSONResponse:
    """RFC 9728 protected-resource metadata, reachable without authentication.

    Tells an MCP client (e.g. Claude) where the authorization server is, so it
    can start the OAuth login flow instead of getting a bare 401.
    """
    settings = get_settings()
    return JSONResponse(
        {
            "resource": f"{settings.mcp_public_base_url}/mcp",
            "authorization_servers": [
                f"{settings.keycloak_url}/realms/{settings.keycloak_realm}"
            ],
            "bearer_methods_supported": ["header"],
        }
    )


def create_app():
    """Build a fresh ASGI app.

    ``streamable_http_app()`` creates a new ``StreamableHTTPSessionManager``
    each call; that manager's lifespan can only run once per instance, so a
    module-level singleton reused across warm Lambda invocations crashes on
    the second request. Call this once per invocation instead.
    """
    new_app = mcp.streamable_http_app(
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=False,
        ),
    )
    new_app.add_middleware(_BearerAuthMiddleware)
    new_app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    new_app.add_route("/health", health)
    new_app.add_route(_PROTECTED_RESOURCE_PATH, oauth_protected_resource)
    return new_app


app = create_app()
