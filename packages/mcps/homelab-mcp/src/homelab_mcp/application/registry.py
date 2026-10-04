"""Tool registry managing upstream tool discovery, catalog caching, and domain lookup."""

import asyncio
import logging

from homelab_mcp.application.guardrail import GuardrailEngine
from homelab_mcp.domain.interfaces.upstream import UpstreamMCPInterface
from homelab_mcp.domain.models.aliases import resolve_canonical_domain
from homelab_mcp.domain.models.upstream import ToolDefinition

logger = logging.getLogger("homelab_mcp.tool_registry")


class ToolRegistry:
    """Registry coordinating tool discovery, cached routing tables, and catalog queries."""

    def __init__(
        self,
        upstreams: dict[str, UpstreamMCPInterface],
        guardrail: GuardrailEngine,
    ):
        self.upstreams = upstreams
        self.guardrail = guardrail
        self._tool_routing: dict[str, tuple[str, UpstreamMCPInterface]] = {}
        self._cached_tools: list[ToolDefinition] | None = None

    async def discover_tools(self, force_refresh: bool = False) -> list[ToolDefinition]:
        """Query all upstream MCP servers in parallel and build the aggregated tool routing table."""
        if self._cached_tools is not None and not force_refresh:
            return self._cached_tools

        aggregated_tools: list[ToolDefinition] = []
        routing: dict[str, tuple[str, UpstreamMCPInterface]] = {}

        async def fetch_upstream(name: str, client: UpstreamMCPInterface):
            try:
                tools = await client.list_tools()
                return name, client, tools
            except Exception as exc:
                logger.warning(f"Failed to discover tools from upstream '{name}': {exc}")
                return name, client, []

        results = await asyncio.gather(
            *[fetch_upstream(name, client) for name, client in self.upstreams.items()]
        )

        for upstream_name, upstream_port, tools in results:
            allowed_count = 0
            for t in tools:
                if self.guardrail.is_tool_allowed(t.name):
                    routing[t.name] = (str(upstream_name), upstream_port)
                    aggregated_tools.append(t)
                    allowed_count += 1

            logger.info(
                f"Discovered {len(tools)} tools from upstream '{upstream_name}' (allowed: {allowed_count})."
            )

        self._tool_routing = routing
        self._cached_tools = aggregated_tools
        return aggregated_tools

    def resolve_tool_routing(self, name: str) -> tuple[str, UpstreamMCPInterface] | None:
        """Resolve a tool name or namespaced identifier to its registered upstream handler."""
        if name in self._tool_routing:
            return self._tool_routing[name]
        if "." in name:
            _, base_name = name.split(".", 1)
            if base_name in self._tool_routing:
                return self._tool_routing[base_name]
        return None

    async def get_domain_tools(self, domain: str) -> list[ToolDefinition]:
        """Retrieve all allowed tools belonging to a specific upstream domain."""
        tools = await self.discover_tools()
        canonical_target = resolve_canonical_domain(domain)
        return [
            t
            for t in tools
            if canonical_target == str(t.upstream_type).lower()
            or canonical_target in str(t.upstream_type).lower()
            or canonical_target in t.name.lower()
        ]
