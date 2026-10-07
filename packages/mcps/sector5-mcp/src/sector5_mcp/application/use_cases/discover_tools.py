"""Use case for discovering and inspecting tools across upstream MCP servers."""

import logging

from sector5_mcp.application.registry import ToolRegistry
from sector5_mcp.domain.models.upstream import ToolDefinition

logger = logging.getLogger("sector5_mcp.application.use_cases.discover_tools")


class DiscoverToolsUseCase:
    """Discovers available tools and filters them by domain or name."""

    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry

    async def execute_all(self, force_refresh: bool = False) -> list[ToolDefinition]:
        """Discover tools across all upstream MCP servers."""
        return await self.registry.discover_tools(force_refresh=force_refresh)

    async def execute_for_domain(self, domain: str) -> list[ToolDefinition]:
        """Retrieve all allowed tools belonging to a specific upstream domain."""
        return await self.registry.get_domain_tools(domain)

    async def execute_get_definition(self, name: str) -> ToolDefinition | None:
        """Return one tool's definition (with parameter schema) by name, or None."""
        base_name = name.split(".", 1)[1] if "." in name else name
        for tool in await self.execute_all():
            if tool.name in (name, base_name):
                return tool
        return None
