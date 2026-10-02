"""FastMCP client infrastructure adapter implementing MCPClientInterface."""

import logging
from typing import Any

from fastmcp import Client
from langchain_core.tools import StructuredTool
from lyoko.config import settings
from lyoko.domain.interfaces import MCPClientInterface

logger = logging.getLogger("lyoko.infrastructure.mcp.client")


class FastMCPClient(MCPClientInterface):
    def __init__(self, server_url: str | None = None, token: str | None = None):
        self.server_url = server_url or settings.mcp_server_url
        raw_token = token if token is not None else settings.service_token
        self.token = (
            raw_token.get_secret_value()
            if hasattr(raw_token, "get_secret_value")
            else str(raw_token)
            if raw_token
            else ""
        )

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        """Call a tool on homelab-mcp gateway, routing upstream tools through gateway_call_tool."""
        auth_token = self.token if self.token else None
        try:
            async with Client(self.server_url, auth=auth_token) as client:
                if name in [
                    "gateway_list_tools",
                    "gateway_list_categories",
                    "gateway_call_tool",
                    "telegram_send_message",
                    "telegram_send_alert",
                ]:
                    res = await client.call_tool(name, arguments)
                    return res.data
                else:
                    res = await client.call_tool(
                        "gateway_call_tool", {"tool_name": name, "arguments": arguments}
                    )
                    return res.data
        except Exception as exc:
            logger.error("Error executing tool %s on FastMCP gateway: %s", name, exc)
            return {"error": str(exc), "status": "failed", "tool": name}

    async def list_categories(self) -> list[dict[str, Any]]:
        """List all connected upstream MCP categories and their available tool counts."""
        auth_token = self.token if self.token else None
        try:
            async with Client(self.server_url, auth=auth_token) as client:
                res = await client.call_tool("gateway_list_categories", {})
                return res.data if isinstance(res.data, list) else []
        except Exception as exc:
            logger.warning("Failed to list categories from FastMCP gateway: %s", exc)
            return []

    async def list_tools(self, upstream: str | None = None) -> list[dict[str, Any]]:
        """List all tools available from gateway and connected upstreams, optionally filtered."""
        auth_token = self.token if self.token else None
        try:
            async with Client(self.server_url, auth=auth_token) as client:
                args = {"upstream": upstream} if upstream else {}
                res = await client.call_tool("gateway_list_tools", args)
                return res.data if isinstance(res.data, list) else []
        except Exception as exc:
            logger.warning("Failed to list tools from FastMCP gateway: %s", exc)
            return []

    def get_langchain_tools(self) -> list[Any]:
        """Return LangChain StructuredTool instances to dynamically discover and execute homelab tools."""

        async def _gateway_list_categories() -> str:
            """Discover all active connected upstream categories and how many tools each provides."""
            categories = await self.list_categories()
            if not categories:
                # Fallback to computing from list_tools
                tools = await self.list_tools()
                counts: dict[str, int] = {}
                for t in tools:
                    k = str(t.get("upstream", "other"))
                    counts[k] = counts.get(k, 0) + 1
                categories = [{"upstream": k, "tool_count": v} for k, v in sorted(counts.items())]
            return str(categories)

        async def _gateway_list_tools(upstream: str | None = None) -> str:
            """List operational tools available in the homelab infrastructure, optionally filtered by upstream category.

            Args:
                upstream: Optional upstream category name to filter (e.g. 'homeassistant', 'unifi', 'kubernetes', 'grafana', 'github').
            """
            tools = await self.list_tools(upstream=upstream)
            return str(
                [
                    {
                        "name": t.get("name"),
                        "description": t.get("description"),
                        "upstream": t.get("upstream"),
                    }
                    for t in tools
                ]
            )

        async def _gateway_call_tool(tool_name: str, arguments: dict[str, Any]) -> str:
            """Execute any operational homelab tool by its exact name with arguments.

            Args:
                tool_name: Exact name of the tool to invoke.
                arguments: Dictionary of parameters matching the tool schema.
            """
            result = await self.call_tool(tool_name, arguments)
            return str(result)

        categories_tool = StructuredTool.from_function(
            coroutine=_gateway_list_categories,
            name="gateway_list_categories",
            description="Discover which upstream services and categories are currently connected and available in the homelab environment (e.g. smart home, network controllers, clusters, metrics).",
        )

        list_tool = StructuredTool.from_function(
            coroutine=_gateway_list_tools,
            name="gateway_list_tools",
            description="List specific operational tools available in the homelab, with optional 'upstream' category filter to quickly find relevant tools without loading the entire catalog.",
        )

        call_tool = StructuredTool.from_function(
            coroutine=_gateway_call_tool,
            name="gateway_call_tool",
            description="Execute any operational homelab tool by name with arguments to fetch live status, manage devices, query metrics, or perform operations.",
        )

        return [categories_tool, list_tool, call_tool]
