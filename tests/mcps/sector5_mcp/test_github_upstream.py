"""Unit and integration tests for GitHub upstream in sector5-mcp."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sector5_mcp.application.service import MCPGatewayService
from sector5_mcp.config import GatewaySettings
from sector5_mcp.domain.interfaces.auth import AuthVerifierInterface
from sector5_mcp.domain.interfaces.upstream import UpstreamMCPInterface
from sector5_mcp.domain.models.upstream import (
    ToolDefinition,
    ToolResult,
    UpstreamType,
)
from sector5_mcp.server import build_gateway_application


@pytest.fixture
def mock_auth():
    auth = MagicMock(spec=AuthVerifierInterface)
    auth.verify.return_value = MagicMock(authenticated=True)
    return auth


@pytest.mark.asyncio
async def test_github_tools_discovery_and_execution(mock_auth):
    mock_github = MagicMock(spec=UpstreamMCPInterface)
    mock_github.list_tools = AsyncMock(
        return_value=[
            ToolDefinition(
                name="github_get_file_contents",
                description="Get repository file contents",
                parameters={"type": "object", "properties": {"repo": {"type": "string"}}},
                upstream_type=UpstreamType.GITHUB,
            ),
            ToolDefinition(
                name="github_get_recent_commits",
                description="List recent commits",
                parameters={"type": "object", "properties": {"repo": {"type": "string"}}},
                upstream_type=UpstreamType.GITHUB,
            ),
        ]
    )
    mock_github.call_tool = AsyncMock(
        return_value=ToolResult(status="success", content="apiVersion: apps/v1...")
    )

    gateway = MCPGatewayService(
        upstreams={UpstreamType.GITHUB: mock_github},
        auth_port=mock_auth,
    )

    tools = await gateway.discover_tools()
    assert len(tools) == 2
    tool_names = [t.name for t in tools]
    assert "github_get_file_contents" in tool_names
    assert "github_get_recent_commits" in tool_names

    res = await gateway.execute_tool(
        "github_get_file_contents",
        {"repo": "csp33/lyoko-ai-ops", "path": "values.yaml"},
    )
    assert res.status == "success"
    assert "apiVersion: apps/v1" in res.content
    mock_github.call_tool.assert_awaited_once_with(
        "github_get_file_contents",
        {"repo": "csp33/lyoko-ai-ops", "path": "values.yaml"},
    )


def test_gateway_settings_github_defaults():
    settings = GatewaySettings()
    assert settings.github_enabled is True
    assert "server-github" in settings.github_command
    assert settings.github_token == ""


def test_build_gateway_application_with_github():
    custom_settings = GatewaySettings(
        ha_enabled=False,
        unifi_enabled=False,
        k8s_enabled=False,
        github_enabled=True,
        github_token="ghp_mock_token_12345",
        github_command="npx -y @modelcontextprotocol/server-github",
        github_owner="csp33",
    )

    with patch("sector5_mcp.server.settings", custom_settings):
        service, app = build_gateway_application()
        assert UpstreamType.GITHUB in service.upstreams
        client = service.upstreams[UpstreamType.GITHUB]
        assert client.command == "npx -y @modelcontextprotocol/server-github"
        assert client.upstream_type == UpstreamType.GITHUB
        assert client.prefix == "github_"
        assert client.env.get("GITHUB_PERSONAL_ACCESS_TOKEN") == "ghp_mock_token_12345"
        assert client.env.get("GITHUB_OWNER") == "csp33"
