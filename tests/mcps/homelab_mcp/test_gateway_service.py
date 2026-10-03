"""Unit tests for MCPGatewayService application layer."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from homelab_mcp.application.service import MCPGatewayService
from homelab_mcp.domain.exceptions.tool import ToolNotFoundError
from homelab_mcp.domain.interfaces.auth import AuthVerifierInterface
from homelab_mcp.domain.interfaces.upstream import UpstreamMCPInterface
from homelab_mcp.domain.models.upstream import (
    ToolDefinition,
    ToolResult,
    UpstreamType,
)


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
                name="pods_get",
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
        "pods_get", {"namespace": "media", "pod_name": "radarr-123"}
    )
    assert result.status == "success"
    assert result.content == {"pod": "running"}
    mock_k8s.call_tool.assert_awaited_once_with(
        "pods_get", {"namespace": "media", "pod_name": "radarr-123"}
    )


@pytest.mark.asyncio
async def test_gateway_tool_not_found_raises(mock_auth):
    gateway = MCPGatewayService(upstreams={}, auth_port=mock_auth)
    with pytest.raises(ToolNotFoundError):
        await gateway.execute_tool("unknown_tool", {})


@pytest.mark.asyncio
async def test_gateway_fastmcp_tools_and_truncation(mock_auth):
    from homelab_mcp.infrastructure.mcp.server import create_gateway_mcp_server

    mock_ha = MagicMock(spec=UpstreamMCPInterface)
    mock_ha.list_tools = AsyncMock(
        return_value=[
            ToolDefinition(
                name="ha_manage_lights",
                description="Turn on/off and configure lighting brightness and rgb colors.\nDetailed instructions here...",
                parameters={"type": "object", "properties": {"entity_id": {"type": "string"}}},
                upstream_type=UpstreamType.HOME_ASSISTANT,
            ),
            ToolDefinition(
                name="ha_get_climate",
                description="Inspect thermostats and climate entities",
                parameters={"type": "object"},
                upstream_type=UpstreamType.HOME_ASSISTANT,
            ),
        ]
    )
    mock_unifi = MagicMock(spec=UpstreamMCPInterface)
    mock_unifi.list_tools = AsyncMock(
        return_value=[
            ToolDefinition(
                name="unifi_list_clients",
                description="List all active and wireless network clients connected to APs",
                parameters={"type": "object"},
                upstream_type=UpstreamType.UNIFI,
            )
        ]
    )
    mock_unifi.call_tool = AsyncMock(
        return_value=ToolResult(
            status="success",
            content="A" * 15000,  # huge output
        )
    )

    gateway = MCPGatewayService(
        upstreams={
            UpstreamType.HOME_ASSISTANT: mock_ha,
            UpstreamType.UNIFI: mock_unifi,
        },
        auth_port=mock_auth,
    )
    mcp = create_gateway_mcp_server(gateway)

    # 1. gateway_list_categories
    cat_res = await mcp.call_tool("gateway_list_categories", {})
    assert not cat_res.is_error
    categories = cat_res.structured_content.get("result", cat_res.structured_content)
    assert len(categories) == 2

    # 2. gateway_list_tools with query
    query_res = await mcp.call_tool("gateway_list_tools", {"query": "light"})
    assert not query_res.is_error
    tools_list = query_res.structured_content.get("result", query_res.structured_content)
    assert len(tools_list) == 1
    assert tools_list[0]["name"] == "ha_manage_lights"
    assert "parameters" not in tools_list[0]  # Parameters omitted from concise listing
    assert (
        tools_list[0]["description"]
        == "Turn on/off and configure lighting brightness and rgb colors."
    )

    # 3. gateway_get_tool_schema
    schema_res = await mcp.call_tool("gateway_get_tool_schema", {"tool_name": "ha_manage_lights"})
    assert not schema_res.is_error
    schema = schema_res.structured_content.get("result", schema_res.structured_content)
    assert schema["name"] == "ha_manage_lights"
    assert "properties" in schema["parameters"]

    # 4. gateway_call_tool with large output truncation
    call_res = await mcp.call_tool(
        "gateway_call_tool", {"tool_name": "unifi_list_clients", "arguments": {}}
    )
    assert not call_res.is_error
    call_data = call_res.structured_content.get("result", call_res.structured_content)
    assert "Output truncated" in call_data["content"]
    assert len(call_data["content"]) < 13000

    # 5. gateway_call_tool with empty output
    mock_ha.call_tool = AsyncMock(
        return_value=ToolResult(
            status="success",
            content="",
        )
    )
    call_empty = await mcp.call_tool(
        "gateway_call_tool", {"tool_name": "ha_get_climate", "arguments": {}}
    )
    assert not call_empty.is_error
    empty_data = call_empty.structured_content.get("result", call_empty.structured_content)
    assert empty_data["content"] == "No resources found or empty result."


@pytest.mark.asyncio
async def test_gateway_search_tools_ranking_and_aliases(mock_auth):
    mock_unifi = MagicMock(spec=UpstreamMCPInterface)
    mock_unifi.list_tools = AsyncMock(
        return_value=[
            ToolDefinition(
                name="unifi_delete_client_group",
                description="Delete a client group by ID. Requires confirmation.",
                upstream_type=UpstreamType.UNIFI,
            ),
            ToolDefinition(
                name="unifi_create_client_group",
                description="Create a client group.",
                upstream_type=UpstreamType.UNIFI,
            ),
            ToolDefinition(
                name="unifi_get_top_clients",
                description="Get a list of top clients by network traffic usage sorted by total bytes",
                upstream_type=UpstreamType.UNIFI,
            ),
            ToolDefinition(
                name="unifi_list_clients",
                description="Returns connected clients with mac, name, hostname, ip, status",
                upstream_type=UpstreamType.UNIFI,
            ),
        ]
    )
    mock_k8s = MagicMock(spec=UpstreamMCPInterface)
    mock_k8s.list_tools = AsyncMock(
        return_value=[
            ToolDefinition(
                name="k8s_resources_get",
                description="Get a Kubernetes resource by apiVersion, kind, and name",
                upstream_type=UpstreamType.KUBERNETES,
            ),
        ]
    )

    gateway = MCPGatewayService(
        upstreams={UpstreamType.UNIFI: mock_unifi, UpstreamType.KUBERNETES: mock_k8s},
        auth_port=mock_auth,
    )

    # 1. Test alias mapping: 'network' -> 'unifi'
    tools_alias = await gateway.search_tools(upstream="network")
    assert len(tools_alias) == 4
    assert all(t.upstream_type == UpstreamType.UNIFI for t in tools_alias)

    # 2. Test multi-token relevance scoring: 'top client traffic' should rank unifi_get_top_clients first
    top_search = await gateway.search_tools(query="top client traffic", upstream="network")
    assert len(top_search) > 0
    assert top_search[0].name == "unifi_get_top_clients"

    # 3. Test read vs mutation preference: searching 'client' should rank list/get tools above delete/create tools
    client_search = await gateway.search_tools(query="client", upstream="unifi")
    assert len(client_search) == 4
    top_two_names = [t.name for t in client_search[:2]]
    assert "unifi_get_top_clients" in top_two_names
    assert "unifi_list_clients" in top_two_names
    # Destructive/creation tools should rank lower
    assert client_search[-1].name in ["unifi_delete_client_group", "unifi_create_client_group"]

    # 4. Test explicit mutation query: searching 'delete client' should rank unifi_delete_client_group first
    delete_search = await gateway.search_tools(query="delete client")
    assert delete_search[0].name == "unifi_delete_client_group"

    # 5. Test get_domain_tools
    domain_tools = await gateway.get_domain_tools("network")
    assert len(domain_tools) == 4
    assert all(t.upstream_type == UpstreamType.UNIFI for t in domain_tools)

    # 6. GitOps / Argo CD aliases resolve to the kubernetes domain
    gitops_tools = await gateway.get_domain_tools("gitops")
    assert [t.name for t in gitops_tools] == ["k8s_resources_get"]
    assert gitops_tools == await gateway.get_domain_tools("kubernetes")
