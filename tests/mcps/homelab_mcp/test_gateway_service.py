"""Unit tests for MCPGatewayService application layer."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from homelab_mcp.application.service import MCPGatewayService
from homelab_mcp.domain.exceptions import ToolNotFoundError
from homelab_mcp.domain.interfaces import AuthVerifierInterface, UpstreamMCPInterface
from homelab_mcp.domain.models import ToolDefinition, ToolResult, UpstreamType


@pytest.fixture
def mock_auth():
    auth = MagicMock(spec=AuthVerifierInterface)
    auth.verify.return_value = MagicMock(authenticated=True)
    return auth


@pytest.mark.asyncio
async def test_gateway_resilient_discovery(mock_auth):
    # Upstream 1: HA is healthy
    mock_ha = MagicMock(spec=UpstreamMCPInterface)
    mock_ha.list_tools = AsyncMock(
        return_value=[
            ToolDefinition(
                name="ha_get_state",
                description="Get state",
                upstream_type=UpstreamType.HOME_ASSISTANT,
            )
        ]
    )

    # Upstream 2: UniFi fails during discovery (e.g. connection timeout)
    mock_unifi = MagicMock(spec=UpstreamMCPInterface)
    mock_unifi.list_tools = AsyncMock(side_effect=ConnectionError("UniFi Controller unreachable"))

    # Upstream 3: K8s is healthy
    mock_k8s = MagicMock(spec=UpstreamMCPInterface)
    mock_k8s.list_tools = AsyncMock(
        return_value=[
            ToolDefinition(
                name="k8s_get_pods", description="List pods", upstream_type=UpstreamType.KUBERNETES
            )
        ]
    )

    gateway = MCPGatewayService(
        upstreams={
            UpstreamType.HOME_ASSISTANT: mock_ha,
            UpstreamType.UNIFI: mock_unifi,
            UpstreamType.KUBERNETES: mock_k8s,
        },
        auth_port=mock_auth,
    )

    tools = await gateway.discover_tools()
    assert len(tools) == 2
    names = [t.name for t in tools]
    assert "ha_get_state" in names
    assert "k8s_get_pods" in names


@pytest.mark.asyncio
async def test_gateway_tool_execution(mock_auth):
    mock_k8s = MagicMock(spec=UpstreamMCPInterface)
    mock_k8s.list_tools = AsyncMock(
        return_value=[
            ToolDefinition(
                name="k8s_get_pod_diagnostics",
                description="Diagnostics",
                upstream_type=UpstreamType.KUBERNETES,
            )
        ]
    )
    mock_k8s.call_tool = AsyncMock(
        return_value=ToolResult(status="success", content={"pod": "running"})
    )

    gateway = MCPGatewayService(
        upstreams={UpstreamType.KUBERNETES: mock_k8s},
        auth_port=mock_auth,
    )

    result = await gateway.execute_tool(
        "k8s_get_pod_diagnostics", {"namespace": "media", "pod_name": "radarr-123"}
    )
    assert result.status == "success"
    assert result.content == {"pod": "running"}
    mock_k8s.call_tool.assert_awaited_once_with(
        "k8s_get_pod_diagnostics", {"namespace": "media", "pod_name": "radarr-123"}
    )


@pytest.mark.asyncio
async def test_gateway_tool_not_found_raises(mock_auth):
    gateway = MCPGatewayService(upstreams={}, auth_port=mock_auth)
    with pytest.raises(ToolNotFoundError):
        await gateway.execute_tool("unknown_tool", {})
