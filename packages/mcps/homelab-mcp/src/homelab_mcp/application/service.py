"""MCP Gateway Application Service coordinating upstream MCP routing, discovery, and guardrails."""

import asyncio
import logging
import re
from typing import Any

from homelab_mcp.application.guardrail import GuardrailEngine
from homelab_mcp.config import settings
from homelab_mcp.domain.exceptions.tool import ToolNotFoundError
from homelab_mcp.domain.interfaces.auth import AuthVerifierInterface
from homelab_mcp.domain.interfaces.upstream import UpstreamMCPInterface
from homelab_mcp.domain.models.auth import AuthIdentity
from homelab_mcp.domain.models.guardrail import GuardrailPolicy
from homelab_mcp.domain.models.upstream import ToolDefinition, ToolResult

logger = logging.getLogger("homelab_mcp.gateway_service")

UPSTREAM_ALIASES: dict[str, str] = {
    # UniFi / Network
    "network": "unifi",
    "networking": "unifi",
    "wifi": "unifi",
    "router": "unifi",
    "switch": "unifi",
    "ap": "unifi",
    # Kubernetes
    "k8s": "kubernetes",
    "kube": "kubernetes",
    "cluster": "kubernetes",
    "pod": "kubernetes",
    "workload": "kubernetes",
    # Home Assistant
    "ha": "homeassistant",
    "hass": "homeassistant",
    "iot": "homeassistant",
    "smart_home": "homeassistant",
    "domotica": "homeassistant",
    # Grafana / Prometheus
    "grafana": "grafana",
    "prometheus": "grafana",
    "metrics": "grafana",
    "monitoring": "grafana",
    "alerts": "grafana",
    # GitHub
    "gh": "github",
    "git": "github",
    "repo": "github",
    # Argo CD / GitOps live as Kubernetes CRDs (argoproj.io)
    "gitops": "kubernetes",
    "argocd": "kubernetes",
    "argo": "kubernetes",
}

READ_PREFIXES = ("get_", "list_", "top_", "describe_", "inspect_", "show_", "fetch_", "find_")
MUTATION_PREFIXES = (
    "create_",
    "delete_",
    "block_",
    "unblock_",
    "update_",
    "set_",
    "apply_",
    "remove_",
    "restart_",
    "patch_",
    "authorize_",
    "forget_",
    "force_",
    "reconnect_",
)
MUTATION_KEYWORDS = {
    "create",
    "delete",
    "block",
    "unblock",
    "remove",
    "update",
    "set",
    "restart",
    "patch",
    "modify",
    "kill",
    "reconnect",
    "authorize",
    "forget",
}


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

    @staticmethod
    def _score_tool(tool: ToolDefinition, query_tokens: list[str], raw_query_clean: str) -> float:
        name_lower = tool.name.lower()
        desc_lower = (tool.description or "").lower()
        upstream_lower = str(tool.upstream_type or "").lower()
        name_words = set(re.findall(r"\w+", name_lower))
        desc_words = set(re.findall(r"\w+", desc_lower))

        score = 0.0

        # Exact full query match
        if name_lower == raw_query_clean:
            score += 100.0
        elif raw_query_clean in name_lower:
            score += 40.0
        elif raw_query_clean in desc_lower:
            score += 20.0

        # Token-level scoring
        matched_tokens = 0
        for token in query_tokens:
            token_matched = False
            if token in name_words:
                score += 15.0
                token_matched = True
            elif token in name_lower:
                score += 8.0
                token_matched = True

            if token in desc_words:
                score += 6.0
                token_matched = True
            elif token in desc_lower:
                score += 2.0
                token_matched = True

            if token in upstream_lower:
                score += 3.0
                token_matched = True

            if token_matched:
                matched_tokens += 1

        # Bonus when multiple tokens match
        if query_tokens and matched_tokens == len(query_tokens):
            score += 25.0 * len(query_tokens)

        # If no tokens or query matched, this tool is irrelevant
        if score == 0.0:
            return 0.0

        # Read vs Mutation Intent
        has_mutation_intent = any(tok in MUTATION_KEYWORDS for tok in query_tokens)
        is_mutation_tool = any(
            name_lower.startswith(p) or f"_{p}" in name_lower for p in MUTATION_PREFIXES
        )
        is_read_tool = any(name_lower.startswith(p) or f"_{p}" in name_lower for p in READ_PREFIXES)

        if has_mutation_intent:
            if is_mutation_tool:
                score += 15.0
        else:
            if is_read_tool:
                score += 15.0
            elif is_mutation_tool:
                score -= 8.0

        return score

    async def search_tools(
        self,
        query: str | None = None,
        upstream: str | None = None,
        limit: int = 25,
    ) -> list[ToolDefinition]:
        """Search and rank tools with multi-token relevance scoring and category alias resolution."""
        tools = await self.discover_tools()

        if upstream:
            raw_target = upstream.strip().lower()
            canonical_target = UPSTREAM_ALIASES.get(raw_target, raw_target)
            tools = [
                t
                for t in tools
                if canonical_target == str(t.upstream_type).lower()
                or canonical_target in str(t.upstream_type).lower()
                or raw_target == str(t.upstream_type).lower()
                or raw_target in str(t.upstream_type).lower()
                or canonical_target in t.name.lower()
                or raw_target in t.name.lower()
            ]

        if query:
            raw_query_clean = query.strip().lower()
            query_tokens = [tok for tok in re.findall(r"\w+", raw_query_clean) if len(tok) > 1]
            if not query_tokens and raw_query_clean:
                query_tokens = [raw_query_clean]

            scored_tools: list[tuple[float, ToolDefinition]] = []
            for t in tools:
                score = self._score_tool(t, query_tokens, raw_query_clean)
                if score > 0:
                    scored_tools.append((score, t))

            # Sort by score desc, then by tool name asc
            scored_tools.sort(key=lambda item: (-item[0], item[1].name))
            tools = [t for _, t in scored_tools]

        bounded_limit = max(1, min(limit, 50))
        return tools[:bounded_limit]

    async def get_domain_tools(self, domain: str) -> list[ToolDefinition]:
        """Retrieve all allowed tools belonging to a specific upstream domain."""
        tools = await self.discover_tools()
        canonical_target = UPSTREAM_ALIASES.get(domain.strip().lower(), domain.strip().lower())
        return [
            t
            for t in tools
            if canonical_target == str(t.upstream_type).lower()
            or canonical_target in str(t.upstream_type).lower()
            or canonical_target in t.name.lower()
        ]

    def _resolve_tool_routing(self, name: str) -> tuple[str, UpstreamMCPInterface] | None:
        """Resolve tool name to its registered upstream handler."""
        if name in self._tool_routing:
            return self._tool_routing[name]
        if "." in name:
            _, base_name = name.split(".", 1)
            if base_name in self._tool_routing:
                return self._tool_routing[base_name]
        return None

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
