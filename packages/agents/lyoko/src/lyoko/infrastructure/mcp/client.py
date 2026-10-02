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

    async def list_tools(self) -> list[dict[str, Any]]:
        """List all tools available from gateway and connected upstreams."""
        auth_token = self.token if self.token else None
        try:
            async with Client(self.server_url, auth=auth_token) as client:
                res = await client.call_tool("gateway_list_tools", {})
                return res.data if isinstance(res.data, list) else []
        except Exception as exc:
            logger.warning("Failed to list tools from FastMCP gateway: %s", exc)
            return []

    def get_langchain_tools(self) -> list[Any]:
        """Return LangChain StructuredTool instances to execute tools via homelab-mcp."""

        async def _gateway_list_tools() -> str:
            """List all tools available in the homelab infrastructure (Home Assistant smart home, UniFi network, Kubernetes, Grafana, Telegram)."""
            tools = await self.list_tools()
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
            """Execute any homelab tool (Home Assistant, UniFi, Kubernetes, Grafana, Telegram).

            Args:
                tool_name: Name of the tool to invoke (e.g., ha_list_floors_areas, ha_manage_pipeline, unifi_execute, etc.)
                arguments: Dictionary of arguments for the tool.
            """
            result = await self.call_tool(tool_name, arguments)
            return str(result)

        list_tool = StructuredTool.from_function(
            coroutine=_gateway_list_tools,
            name="gateway_list_tools",
            description="Discover all available tools in the Homelab AIOps platform (Home Assistant smart home devices, UniFi network controllers, Kubernetes cluster pods, Grafana metrics, Telegram alerts).",
        )

        call_tool = StructuredTool.from_function(
            coroutine=_gateway_call_tool,
            name="gateway_call_tool",
            description="Execute any Homelab AIOps tool by name with arguments (e.g. Home Assistant devices, UniFi network clients, Kubernetes pods/logs, Grafana dashboards, Telegram alerts).",
        )

        return [list_tool, call_tool]
