"""AWS Lambda entry point wrapping the ASGI app with Mangum.

Builds a fresh app (and Mangum instance) on every invocation: Mangum runs the
ASGI lifespan on each call, but the MCP session manager backing the app can
only run its lifespan once per instance — reusing one across warm
invocations crashes on the second request. See ``server.create_app``.
"""

from mangum import Mangum

from pantry_mcp.server import create_app


def handler(event, context):
    """Lambda entry point: build a fresh app + Mangum wrapper for this invocation."""
    return Mangum(create_app())(event, context)
