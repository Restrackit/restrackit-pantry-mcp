"""MCP server exposing the pantry tools over streamable HTTP, bearer-protected.

Uses ``mcp`` 2.x, where the v1 ``FastMCP`` class was renamed ``MCPServer``
(module ``mcp.server.mcpserver``); the ``.tool()`` decorator and
``.streamable_http_app()`` method keep the same signature as v1, so only the
import needs adapting.
"""

from mcp.server.mcpserver import MCPServer
from starlette.middleware.base import BaseHTTPMiddleware
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
async def add_purchase(items: list[pantry.PurchaseItem]) -> dict:
    """Record a purchase: creates products/categories/storage methods as needed, one batch per unit."""
    return await pantry.add_purchase(_get_client(), items)


@mcp.tool()
async def get_pantry_status(product_name: str | None = None) -> dict[str, int]:
    """Return the available quantity per product (all products, or one if specified)."""
    return await pantry.get_pantry_status(_get_client(), product_name)


@mcp.tool()
async def record_consumption(product_name: str, quantity: int) -> dict:
    """Close `quantity` open units of a product (oldest first)."""
    return await pantry.record_consumption(_get_client(), product_name, quantity)


class _BearerAuthMiddleware(BaseHTTPMiddleware):
    """Require a valid bearer token on every route except ``/health``."""

    async def dispatch(self, request: Request, call_next):
        """Reject requests missing or mismatching the configured bearer token."""
        if request.url.path == "/health":
            return await call_next(request)

        expected = f"Bearer {get_settings().mcp_auth_token}"
        if request.headers.get("Authorization") != expected:
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        return await call_next(request)


async def health(request: Request) -> JSONResponse:
    """Liveness check, reachable without authentication."""
    return JSONResponse({"status": "ok"})


app = mcp.streamable_http_app()
app.add_middleware(_BearerAuthMiddleware)
app.add_route("/health", health)
