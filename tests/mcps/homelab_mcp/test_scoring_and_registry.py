"""Unit tests for tool scoring, aliases, and ToolRegistry."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from homelab_mcp.application.guardrail import GuardrailEngine
from homelab_mcp.application.registry import ToolRegistry
from homelab_mcp.application.scoring import score_tool
from homelab_mcp.domain.interfaces.upstream import UpstreamMCPInterface
from homelab_mcp.domain.models.aliases import UPSTREAM_ALIASES, resolve_canonical_domain
from homelab_mcp.domain.models.guardrail import GuardrailPolicy
from homelab_mcp.domain.models.upstream import ToolDefinition, UpstreamType


def test_resolve_canonical_domain():
    assert resolve_canonical_domain("k8s") == "kubernetes"
    assert resolve_canonical_domain("wifi") == "unifi"
    assert resolve_canonical_domain("ha") == "homeassistant"
    assert resolve_canonical_domain("gitops") == "kubernetes"
    assert resolve_canonical_domain("unknown_custom") == "unknown_custom"
    assert "router" in UPSTREAM_ALIASES


def test_score_tool_exact_and_token_matches():
    tool = ToolDefinition(
        name="k8s_get_pods",
        description="List all Kubernetes pods across namespaces",
        upstream_type=UpstreamType.KUBERNETES,
    )
    exact_score = score_tool(tool, ["k8s_get_pods"], "k8s_get_pods")
    assert exact_score >= 100.0

    token_score = score_tool(tool, ["pods", "kubernetes"], "pods kubernetes")
    assert token_score > 0.0

    irrelevant_score = score_tool(tool, ["unifi", "switch"], "unifi switch")
    assert irrelevant_score == 0.0


@pytest.mark.asyncio
async def test_tool_registry_discovery_and_search():
    guardrail = GuardrailEngine(GuardrailPolicy())
    mock_ha = MagicMock(spec=UpstreamMCPInterface)
    mock_ha.list_tools = AsyncMock(
        return_value=[
            ToolDefinition(
                name="ha_get_state",
                description="Get state of an entity",
                upstream_type=UpstreamType.HOME_ASSISTANT,
            )
        ]
    )

    registry = ToolRegistry(
        upstreams={UpstreamType.HOME_ASSISTANT: mock_ha},
        guardrail=guardrail,
    )

    tools = await registry.discover_tools()
    assert len(tools) == 1
    assert tools[0].name == "ha_get_state"

    # Search with domain alias
    results = await registry.search_tools(query="state", upstream="iot")
    assert len(results) == 1
    assert results[0].name == "ha_get_state"

    # Route resolution
    route = registry.resolve_tool_routing("ha_get_state")
    assert route is not None
    assert route[0] == UpstreamType.HOME_ASSISTANT
