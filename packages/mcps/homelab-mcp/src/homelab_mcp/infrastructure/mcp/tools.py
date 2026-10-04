"""Gateway MCP tool handlers for domain discovery and execution."""

from typing import Any

from fastmcp import FastMCP
from homelab_mcp.application.service import MCPGatewayService
from homelab_mcp.domain.models.upstream import UpstreamType
from homelab_mcp.infrastructure.mcp.formatting import lean_tool_index, shape_tool_content

_MAX_DOMAIN_PAGE = 100


def register_gateway_tools(mcp: FastMCP, service: MCPGatewayService) -> None:
    """Register the domain discovery and tool execution handlers on the MCP server."""

    @mcp.tool()
    async def gateway_get_domain_tools(
        domain: UpstreamType,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Return one page of the tool index for one upstream domain.

        Returns a lean index (name, one-line description, upstream) so a large domain does not
        flood the context. Page with ``limit``/``offset`` and follow ``has_more``. Use
        gateway_get_tool_schema(tool_name) for the exact arguments before executing with
        gateway_call_tool.

        Args:
            domain: Upstream domain (e.g. kubernetes, unifi, homeassistant, grafana, github, telegram).
            limit: Maximum tools to return in this page (default 50, max 100).
            offset: Number of tools to skip for pagination (default 0).
        """
        tools = await service.get_domain_tools(domain)
        total = len(tools)
        if total == 0:
            return {
                "error": (
                    f"No tools for domain '{str(domain)}'. "
                    "It may be disabled, empty, or not configured."
                )
            }
        bounded_limit = max(1, min(limit, _MAX_DOMAIN_PAGE))
        bounded_offset = max(0, offset)
        page = tools[bounded_offset : bounded_offset + bounded_limit]
        return {
            "domain": str(domain),
            "total": total,
            "limit": bounded_limit,
            "offset": bounded_offset,
            "has_more": bounded_offset + len(page) < total,
            "tools": lean_tool_index(page),
        }

    @mcp.tool()
    async def gateway_get_tool_schema(tool_name: str) -> dict[str, Any]:
        """Get the full parameter schema and detailed description for a specific operational tool.

        Args:
            tool_name: The exact name of the tool to inspect.
        """
        base_name = tool_name.split(".", 1)[1] if "." in tool_name else tool_name
        tools = await service.discover_tools()
        for t in tools:
            if t.name in (tool_name, base_name):
                return {
                    "name": t.name,
                    "description": t.description,
                    "upstream": str(t.upstream_type),
                    "parameters": t.parameters,
                }
        return {"error": f"Tool '{tool_name}' not found."}

    @mcp.tool()
    async def gateway_call_tool(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Execute any tool across the connected upstream MCP servers with authentication and guardrails.

        Args:
            tool_name: Name of the upstream tool to invoke.
            arguments: Dictionary of arguments matching the tool schema.
        """
        result = await service.execute_tool(tool_name, arguments)
        return {
            "status": result.status,
            "content": shape_tool_content(result.content, result.is_error),
            "is_error": result.is_error,
        }
