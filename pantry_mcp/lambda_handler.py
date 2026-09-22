"""AWS Lambda entry point wrapping the ASGI app with Mangum."""

from mangum import Mangum

from pantry_mcp.server import app

handler = Mangum(app)
