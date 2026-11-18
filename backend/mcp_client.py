"""Small synchronous adapter around the official MCP Python client."""

import asyncio
import os

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


class MCPClient:
    """Call only the configured MCP server over Streamable HTTP."""

    ALLOWED_TOOLS = {"calculator"}

    def __init__(self, server_url: str):
        self.server_url = server_url

    @classmethod
    def from_env(cls):
        return cls(os.environ.get("MCP_SERVER_URL", "http://127.0.0.1:8000/mcp"))

    async def _call(self, name: str, arguments: dict):
        async with streamablehttp_client(self.server_url) as (read_stream, write_stream, _):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                return await session.call_tool(name, arguments)

    def call_tool(self, name: str, arguments: dict, timeout: float = 5.0) -> dict:
        if name not in self.ALLOWED_TOOLS:
            return {"ok": False, "error": {"code": "tool_not_allowed", "message": "Tool is not allow-listed."}}
        if not isinstance(arguments, dict) or set(arguments) != {"expression"} or not isinstance(arguments["expression"], str):
            return {"ok": False, "error": {"code": "invalid_arguments", "message": "calculator requires a string expression."}}
        try:
            response = asyncio.run(asyncio.wait_for(self._call(name, arguments), timeout=timeout))
            structured = getattr(response, "structuredContent", None)
            if structured is None:
                structured = getattr(response, "structured_content", None)
            if isinstance(structured, dict) and "ok" in structured:
                return structured
            # Compatibility with SDK releases that expose only text content.
            for item in getattr(response, "content", []):
                if getattr(item, "type", None) == "text":
                    import json
                    parsed = json.loads(item.text)
                    if isinstance(parsed, dict) and "ok" in parsed:
                        return parsed
            return {"ok": False, "error": {"code": "invalid_tool_response", "message": "MCP tool returned no structured result."}}
        except asyncio.TimeoutError:
            return {"ok": False, "error": {"code": "timeout", "message": "MCP tool call timed out."}}
        except Exception as exc:
            return {"ok": False, "error": {"code": "mcp_unavailable", "message": str(exc)[:300]}}
