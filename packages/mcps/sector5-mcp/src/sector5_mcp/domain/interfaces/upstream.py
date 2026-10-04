"""Upstream MCP server interface definitions."""

from abc import ABC, abstractmethod
from typing import Any

from sector5_mcp.domain.models.upstream import ToolDefinition, ToolResult


class UpstreamMCPInterface(ABC):
    @abstractmethod
    async def list_tools(self) -> list[ToolDefinition]:
        """Fetch all available tools from the upstream MCP server."""

    @abstractmethod
    async def call_tool(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        """Execute a tool on the upstream MCP server."""
