"""Upstream MCP server interface definitions."""

from abc import ABC, abstractmethod
from typing import Any

from homelab_mcp.domain.models import ToolDefinition, ToolResult


class UpstreamMCPInterface(ABC):
    @abstractmethod
    async def list_tools(self) -> list[ToolDefinition]:
        """Fetch all available tools from the upstream MCP server."""

    @abstractmethod
    async def call_tool(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        """Execute a tool on the upstream MCP server."""
