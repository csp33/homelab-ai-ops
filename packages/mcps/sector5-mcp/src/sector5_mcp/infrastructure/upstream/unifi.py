"""UniFi Upstream MCP Adapter handling subtool index discovery and unifi_execute wrapping."""

import json
import logging
from typing import Any

from sector5_mcp.domain.models.upstream import ToolDefinition, ToolResult
from sector5_mcp.infrastructure.upstream.client import ProcessUpstreamClient

logger = logging.getLogger("sector5_mcp.upstream_unifi")

UNIFI_ROOT_TOOLS = {
    "unifi_tool_index",
    "unifi_execute",
    "unifi_batch",
    "unifi_batch_status",
    "unifi_load_tools",
    "unifi_get_support_bundle",
}


class UnifiUpstreamClient(ProcessUpstreamClient):
    """Adapter for UniFi Network MCP server expanding subtools from unifi_tool_index."""

    async def list_tools(self) -> list[ToolDefinition]:
        """Discover tools and expand subtools from unifi_tool_index."""
        tools = await super().list_tools()
        if not any(t.name == "unifi_tool_index" for t in tools):
            return tools

        existing_names = {t.name for t in tools}
        try:
            index_res = await self.call_tool("unifi_tool_index", {})
            if index_res and not index_res.is_error and index_res.content:
                content = index_res.content
                if isinstance(content, str):
                    content = json.loads(content)
                if isinstance(content, dict):
                    for sub_tool in content.get("tools", []):
                        st_name = sub_tool.get("name")
                        if st_name and st_name not in existing_names:
                            existing_names.add(st_name)
                            tools.append(
                                ToolDefinition(
                                    name=st_name,
                                    description=sub_tool.get("description", ""),
                                    parameters=sub_tool.get("parameters", {}),
                                    upstream_type=self.upstream_type,
                                )
                            )
        except Exception as exc:
            logger.warning(f"Failed to expand UniFi domain tools from tool_index: {exc}")

        return tools

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        """Execute UniFi tool, routing subtools transparently via unifi_execute."""
        if name.startswith("unifi_") and name not in UNIFI_ROOT_TOOLS:
            logger.debug(f"Routing UniFi subtool '{name}' via 'unifi_execute'...")
            return await super().call_tool("unifi_execute", {"tool": name, "arguments": arguments})
        return await super().call_tool(name, arguments)
