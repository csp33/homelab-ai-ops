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


def _extract_parameters(sub_tool: dict[str, Any]) -> dict[str, Any]:
    """Resolve a subtool's input JSON schema from the several shapes the index may use.

    ``unifi_tool_index`` nests the schema under ``schema.input`` when ``include_schemas`` is
    enabled, but older builds may expose a flat ``parameters``/``schema.input_schema`` key.
    Without this, every subtool would register an empty schema and agents would see no arguments.
    """
    flattened = sub_tool.get("parameters")
    if isinstance(flattened, dict) and flattened:
        return flattened

    schema = sub_tool.get("schema")
    if isinstance(schema, dict):
        for key in ("input", "input_schema"):
            candidate = schema.get(key)
            if isinstance(candidate, dict) and candidate:
                return candidate

    return {}


class UnifiUpstreamClient(ProcessUpstreamClient):
    """Adapter for UniFi Network MCP server expanding subtools from unifi_tool_index."""

    async def list_tools(self) -> list[ToolDefinition]:
        """Discover tools and expand subtools from unifi_tool_index.

        The index is requested with ``include_schemas=True`` so every expanded subtool carries
        its real JSON argument schema. Otherwise agents see bare ``tool()`` signatures, cannot
        discover filter arguments, and the gateway's argument-error self-correction returns an
        empty schema.
        """
        tools = await super().list_tools()
        if not any(t.name == "unifi_tool_index" for t in tools):
            return tools

        existing_names = {t.name for t in tools}
        try:
            index_res = await self.call_tool("unifi_tool_index", {"include_schemas": True})
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
                                    parameters=_extract_parameters(sub_tool),
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
