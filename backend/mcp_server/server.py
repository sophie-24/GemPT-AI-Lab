"""MCP calculator service using the official Python SDK and Streamable HTTP."""

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.responses import JSONResponse
from starlette.routing import Route
import uvicorn

from tools.calculator import calculate


mcp = FastMCP(
    "GemPT calculator",
    stateless_http=True,
    json_response=True,
    transport_security=TransportSecuritySettings(
        allowed_hosts=["mcp-tools:8000", "localhost:8000", "127.0.0.1:8000"]
    ),
)


@mcp.tool()
def calculator(expression: str) -> dict:
    """Evaluate a bounded arithmetic expression. Supports numbers and +, -, *, /, //, %, **."""
    return calculate(expression)


async def healthz(_request):
    return JSONResponse({"status": "ok", "service": "mcp-tools"})


app = mcp.streamable_http_app()
app.routes.append(Route("/healthz", healthz, methods=["GET"]))


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
