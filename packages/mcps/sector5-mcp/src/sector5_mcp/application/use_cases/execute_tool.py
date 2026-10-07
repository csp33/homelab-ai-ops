"""Use case for validating guardrails and executing tools on upstream MCP servers."""

import logging
from typing import Any

from sector5_mcp.application.guardrail import GuardrailEngine
from sector5_mcp.application.registry import ToolRegistry
from sector5_mcp.domain.exceptions.tool import ToolNotFoundError
from sector5_mcp.domain.models.upstream import ToolResult

logger = logging.getLogger("sector5_mcp.application.use_cases.execute_tool")


class ExecuteToolUseCase:
    """Validates guardrails and executes a tool on the resolved upstream MCP server."""

    def __init__(self, registry: ToolRegistry, guardrail: GuardrailEngine) -> None:
        self.registry = registry
        self.guardrail = guardrail

    async def execute(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        """Validate safety guardrails and route tool execution to the upstream MCP server."""
        route = self.registry.resolve_tool_routing(name)
        if route is None:
            # Re-attempt discovery in case tools were registered dynamically
            await self.registry.discover_tools()
            route = self.registry.resolve_tool_routing(name)

        if route is None:
            raise ToolNotFoundError(
                f"Tool '{name}' not found on any upstream MCP server or blocked by policy."
            )

        upstream_name, upstream_client = route

        # Enforce all active security guardrails (namespace, command exec whitelist/blacklist, tool rules)
        self.guardrail.validate_tool_call(name, arguments, upstream_name=upstream_name)

        logger.info(f"Routing tool '{name}' to upstream '{upstream_name}'...")
        return await upstream_client.call_tool(name, arguments)
