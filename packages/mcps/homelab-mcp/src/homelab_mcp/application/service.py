"""Application service orchestrating upstream MCP tool aggregation, routing, and guardrails."""

import logging
from typing import Any

from homelab_mcp.application.guardrail import GuardrailEngine
from homelab_mcp.config import settings
from homelab_mcp.domain.exceptions import ToolNotFoundError
from homelab_mcp.domain.interfaces import AuthVerifierInterface, UpstreamMCPInterface
from homelab_mcp.domain.models import AuthIdentity, GuardrailPolicy, ToolDefinition, ToolResult

logger = logging.getLogger("homelab_mcp.gateway_service")


class MCPGatewayService:
    """Core application service managing upstream MCP routing and security guardrails."""

    def __init__(
        self,
        upstreams: dict[str, UpstreamMCPInterface],
        auth_port: AuthVerifierInterface,
        guardrail_engine: GuardrailEngine | None = None,
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
            )
        )
        self._tool_routing: dict[str, tuple[str, UpstreamMCPInterface]] = {}

    def verify_access(self, token: str | None) -> AuthIdentity:
        return self.auth.verify(token)

    async def discover_tools(self) -> list[ToolDefinition]:
        """Query all upstream MCP servers and build the aggregated tool routing table, filtered by guardrails."""
        aggregated_tools: list[ToolDefinition] = []
        routing: dict[str, tuple[str, UpstreamMCPInterface]] = {}

        for upstream_name, upstream_port in self.upstreams.items():
            try:
                tools = await upstream_port.list_tools()
                for t in tools:
                    # Filter tool discovery through whitelist/guardrail
                    if self.guardrail.is_tool_allowed(t.name):
                        routing[t.name] = (upstream_name, upstream_port)
                        aggregated_tools.append(t)
                    else:
                        logger.debug(
                            f"Tool '{t.name}' from upstream '{upstream_name}' excluded by guardrail policy."
                        )
                logger.info(
                    f"Discovered {len(tools)} tools from upstream '{upstream_name}' (allowed: {sum(1 for t in tools if t.name in routing)})."
                )
            except Exception as exc:
                logger.warning(f"Failed to discover tools from upstream '{upstream_name}': {exc}")

        self._tool_routing = routing
        return aggregated_tools

    async def execute_tool(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        """Validate safety guardrails and route tool execution to the upstream MCP server."""
        if name not in self._tool_routing:
            # Re-attempt quick discovery in case tools were registered dynamically
            await self.discover_tools()

        if name not in self._tool_routing:
            raise ToolNotFoundError(
                f"Tool '{name}' not found on any upstream MCP server or blocked by policy."
            )

        upstream_name, upstream_client = self._tool_routing[name]

        # Enforce all active security guardrails (namespace, command exec whitelist/blacklist, tool rules)
        self.guardrail.validate_tool_call(name, arguments, upstream_name=upstream_name)

        logger.info(f"Routing tool '{name}' to upstream '{upstream_name}'...")
        return await upstream_client.call_tool(name, arguments)
