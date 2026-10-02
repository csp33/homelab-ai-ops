import asyncio
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
                allowed_github_repos=settings.github_allowed_repos,
                blocked_github_repos=settings.github_blocked_repos,
            )
        )
        self._tool_routing: dict[str, tuple[str, UpstreamMCPInterface]] = {}
        self._cached_tools: list[ToolDefinition] | None = None

    def verify_access(self, token: str | None) -> AuthIdentity:
        return self.auth.verify(token)

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
            for t in tools:
                if self.guardrail.is_tool_allowed(t.name):
                    routing[t.name] = (upstream_name, upstream_port)
                    aggregated_tools.append(t)

            # If upstream provides unifi_tool_index, expand domain tools for transparent discovery
            if any(t.name == "unifi_tool_index" for t in tools):
                try:
                    import json

                    index_res = await upstream_port.call_tool("unifi_tool_index", {})
                    if index_res and not index_res.is_error:
                        content = index_res.content
                        if isinstance(content, str):
                            content = json.loads(content)
                        if isinstance(content, dict):
                            for sub_tool in content.get("tools", []):
                                st_name = sub_tool.get("name")
                                if (
                                    st_name
                                    and st_name not in routing
                                    and self.guardrail.is_tool_allowed(st_name)
                                ):
                                    routing[st_name] = (upstream_name, upstream_port)
                                    aggregated_tools.append(
                                        ToolDefinition(
                                            name=st_name,
                                            description=sub_tool.get("description", ""),
                                            parameters={},
                                            upstream_type=tools[0].upstream_type
                                            if tools
                                            else "unifi",
                                        )
                                    )
                except Exception as exc:
                    logger.warning(f"Failed to expand UniFi domain tools from tool_index: {exc}")

            logger.info(
                f"Discovered {len(tools)} tools from upstream '{upstream_name}' (allowed: {sum(1 for t in tools if t.name in routing)})."
            )

        self._tool_routing = routing
        self._cached_tools = aggregated_tools
        return aggregated_tools

    async def execute_tool(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        """Validate safety guardrails and route tool execution to the upstream MCP server."""
        if name not in self._tool_routing:
            # Re-attempt quick discovery in case tools were registered dynamically
            await self.discover_tools()

        if (
            name not in self._tool_routing
            and name.startswith("unifi_")
            and "unifi_execute" in self._tool_routing
        ):
            upstream_name, upstream_client = self._tool_routing["unifi_execute"]
            self.guardrail.validate_tool_call(name, arguments, upstream_name=upstream_name)
            logger.info(f"Routing '{name}' via 'unifi_execute'...")
            return await upstream_client.call_tool(
                "unifi_execute", {"tool": name, "arguments": arguments}
            )

        if name not in self._tool_routing:
            raise ToolNotFoundError(
                f"Tool '{name}' not found on any upstream MCP server or blocked by policy."
            )

        upstream_name, upstream_client = self._tool_routing[name]

        # Enforce all active security guardrails (namespace, command exec whitelist/blacklist, tool rules)
        self.guardrail.validate_tool_call(name, arguments, upstream_name=upstream_name)

        if (
            name.startswith("unifi_")
            and name
            not in [
                "unifi_tool_index",
                "unifi_execute",
                "unifi_batch",
                "unifi_batch_status",
                "unifi_load_tools",
                "unifi_get_support_bundle",
            ]
            and "unifi_execute" in self._tool_routing
        ):
            logger.info(f"Routing UniFi sub-tool '{name}' via 'unifi_execute'...")
            return await upstream_client.call_tool(
                "unifi_execute", {"tool": name, "arguments": arguments}
            )

        logger.info(f"Routing tool '{name}' to upstream '{upstream_name}'...")
        return await upstream_client.call_tool(name, arguments)
