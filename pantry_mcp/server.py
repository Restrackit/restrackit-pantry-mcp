"""MCP server exposing the pantry tools over streamable HTTP, bearer-protected.

Uses ``mcp`` 2.x, where the v1 ``FastMCP`` class was renamed ``MCPServer``
(module ``mcp.server.mcpserver``); the ``.tool()`` decorator and
``.streamable_http_app()`` method keep the same signature as v1, so only the
import needs adapting.
"""

from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from pantry_mcp import pantry
from pantry_mcp.auth import TokenProvider
from pantry_mcp.config import get_settings
from pantry_mcp.restrackit_client import RestrackitClient

mcp = MCPServer("restrackit-pantry-mcp")


def _get_client() -> RestrackitClient:
    settings = get_settings()
    return RestrackitClient(settings, TokenProvider(settings))


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
    return await pantry.add_purchase(_get_client(), items)


@mcp.tool()
async def get_pantry_status(product_name: str | None = None) -> dict[str, int]:
    """Return the available quantity per product (all products, or one if specified)."""
    return await pantry.get_pantry_status(_get_client(), product_name)


@mcp.tool()
async def record_consumption(product_name: str, quantity: int) -> dict[str, Any]:
    """Close `quantity` open units of a product (oldest first)."""
    return await pantry.record_consumption(_get_client(), product_name, quantity)


class _BearerAuthMiddleware(BaseHTTPMiddleware):
    """Require a valid bearer token on every route except ``/health``."""

    async def dispatch(self, request: Request, call_next):
        """Reject requests missing or mismatching the configured bearer token."""
        if request.url.path == "/health" or request.method == "OPTIONS":
            return await call_next(request)

        expected = f"Bearer {get_settings().mcp_auth_token}"
        if request.headers.get("Authorization") != expected:
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        return await call_next(request)


async def health(request: Request) -> JSONResponse:
    """Liveness check, reachable without authentication."""
    return JSONResponse({"status": "ok"})


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
    return new_app


app = create_app()
