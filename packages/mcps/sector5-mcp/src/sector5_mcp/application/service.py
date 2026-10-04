"""MCP Gateway Application Service coordinating upstream MCP routing, discovery, and guardrails."""

import logging
from typing import Any

from sector5_mcp.application.guardrail import GuardrailEngine
from sector5_mcp.application.registry import ToolRegistry
from sector5_mcp.config import settings
from sector5_mcp.domain.exceptions.tool import ToolNotFoundError
from sector5_mcp.domain.interfaces.auth import AuthVerifierInterface
from sector5_mcp.domain.interfaces.upstream import UpstreamMCPInterface
from sector5_mcp.domain.models.auth import AuthIdentity
from sector5_mcp.domain.models.guardrail import GuardrailPolicy
from sector5_mcp.domain.models.upstream import ToolDefinition, ToolResult

logger = logging.getLogger("sector5_mcp.gateway_service")

__all__ = ["MCPGatewayService"]


class MCPGatewayService:
    """Core application service managing upstream MCP routing and security guardrails."""

    def __init__(
        self,
        upstreams: dict[str, UpstreamMCPInterface],
        auth_port: AuthVerifierInterface,
        guardrail_engine: GuardrailEngine | None = None,
        tool_registry: ToolRegistry | None = None,
    ):
        self.upstreams = upstreams
        self.auth = auth_port
        self.guardrail = guardrail_engine or GuardrailEngine(
            GuardrailPolicy(
                allowed_tools=settings.allowed_tools,
                blocked_tools=settings.blocked_tools,
                allowed_exec_commands=settings.allowed_exec_commands,
                blocked_exec_patterns=settings.blocked_exec_patterns,
                blocked_namespaces=settings.blocked_namespaces,
                allowed_github_repos=settings.github_allowed_repos,
                blocked_github_repos=settings.github_blocked_repos,
            )
        )
        self.registry = tool_registry or ToolRegistry(
            upstreams=self.upstreams,
            guardrail=self.guardrail,
        )

    def verify_access(self, token: str | None) -> AuthIdentity:
        """Verify client authentication credentials via the injected auth port."""
        return self.auth.verify(token)

    async def discover_tools(self, force_refresh: bool = False) -> list[ToolDefinition]:
        """Discover tools across all upstream MCP servers."""
        return await self.registry.discover_tools(force_refresh=force_refresh)

    async def get_domain_tools(self, domain: str) -> list[ToolDefinition]:
        """Retrieve all allowed tools belonging to a specific upstream domain."""
        return await self.registry.get_domain_tools(domain)

    async def get_tool_definition(self, name: str) -> ToolDefinition | None:
        """Return one tool's definition (with its parameter schema) by name, or None."""
        base_name = name.split(".", 1)[1] if "." in name else name
        for tool in await self.discover_tools():
            if tool.name in (name, base_name):
                return tool
        return None

    def _resolve_tool_routing(self, name: str) -> tuple[str, UpstreamMCPInterface] | None:
        """Resolve a tool name to its registered upstream handler."""
        return self.registry.resolve_tool_routing(name)

    async def execute_tool(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        """Validate safety guardrails and route tool execution to the upstream MCP server."""
        route = self._resolve_tool_routing(name)
        if route is None:
            # Re-attempt discovery in case tools were registered dynamically
            await self.discover_tools()
            route = self._resolve_tool_routing(name)

        if route is None:
            raise ToolNotFoundError(
                f"Tool '{name}' not found on any upstream MCP server or blocked by policy."
            )

        upstream_name, upstream_client = route

        # Enforce all active security guardrails (namespace, command exec whitelist/blacklist, tool rules)
        self.guardrail.validate_tool_call(name, arguments, upstream_name=upstream_name)

        logger.info(f"Routing tool '{name}' to upstream '{upstream_name}'...")
        return await upstream_client.call_tool(name, arguments)
