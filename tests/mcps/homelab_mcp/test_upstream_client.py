"""Unit tests for ProcessUpstreamClient stdio parameter construction and MCP SDK integration."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homelab_mcp.domain.models.upstream import UpstreamType
from homelab_mcp.infrastructure.upstream.client import ProcessUpstreamClient


def test_process_upstream_client_params():
    client = ProcessUpstreamClient(
        command="kubernetes-mcp-server",
        args=["--namespace", "default"],
        env={"KUBECONFIG": "/tmp/kubeconfig"},
        upstream_type=UpstreamType.KUBERNETES,
    )

    assert client.command == "kubernetes-mcp-server"
    assert client.args == ["--namespace", "default"]
    assert client.upstream_type == UpstreamType.KUBERNETES

    params = client._get_server_params()
    assert params.command == "kubernetes-mcp-server"
    assert params.args == ["--namespace", "default"]
    assert params.env["KUBECONFIG"] == "/tmp/kubeconfig"


def test_process_upstream_client_params_multi_word_command():
    client = ProcessUpstreamClient(
        command="npx -y @grafana/mcp-server@latest",
        upstream_type=UpstreamType.GRAFANA,
    )

    params = client._get_server_params()
    assert params.command == "npx"
    assert params.args == ["-y", "@grafana/mcp-server@latest"]


def test_process_upstream_client_params_multi_word_with_args():
    client = ProcessUpstreamClient(
        command="npx -y @modelcontextprotocol/server-github",
        args=["--verbose"],
        upstream_type=UpstreamType.GITHUB,
    )

    params = client._get_server_params()
    assert params.command == "npx"
    assert params.args == ["-y", "@modelcontextprotocol/server-github", "--verbose"]


@pytest.mark.asyncio
async def test_list_tools_reads_input_schema():
    client = ProcessUpstreamClient(
        command="k8s",
        upstream_type=UpstreamType.KUBERNETES,
    )

    tool1 = SimpleNamespace(
        name="k8s_get_pods",
        description="List pods",
        input_schema={"type": "object", "properties": {"namespace": {"type": "string"}}},
    )
    tool2 = SimpleNamespace(
        name="k8s_get_nodes",
        description=None,
        input_schema={},
    )

    mock_session = AsyncMock()
    mock_session.list_tools.return_value = SimpleNamespace(tools=[tool1, tool2])

    with (
        patch("homelab_mcp.infrastructure.upstream.client.stdio_client") as mock_stdio,
        patch("homelab_mcp.infrastructure.upstream.client.ClientSession") as mock_session_cls,
    ):
        mock_stdio.return_value.__aenter__.return_value = (MagicMock(), MagicMock())
        mock_stdio.return_value.__aexit__.return_value = None
        mock_session_cls.return_value.__aenter__.return_value = mock_session
        mock_session_cls.return_value.__aexit__.return_value = None

        tools = await client.list_tools()

        assert len(tools) == 2
        assert tools[0].name == "k8s_get_pods"
        assert tools[0].parameters == {
            "type": "object",
            "properties": {"namespace": {"type": "string"}},
        }
        assert tools[0].description == "List pods"
        assert tools[1].name == "k8s_get_nodes"
        assert tools[1].parameters == {}
        assert tools[1].description == ""


@pytest.mark.asyncio
async def test_call_tool_handles_is_error_and_text_content():
    client = ProcessUpstreamClient(
        command="k8s",
        upstream_type=UpstreamType.KUBERNETES,
    )

    # In MCP SDK v2, is_error can be None or False on success
    mock_result = SimpleNamespace(
        content=[SimpleNamespace(text="pod-1"), SimpleNamespace(text="pod-2")],
        is_error=None,
    )

    mock_session = AsyncMock()
    mock_session.call_tool.return_value = mock_result

    with (
        patch("homelab_mcp.infrastructure.upstream.client.stdio_client") as mock_stdio,
        patch("homelab_mcp.infrastructure.upstream.client.ClientSession") as mock_session_cls,
    ):
        mock_stdio.return_value.__aenter__.return_value = (MagicMock(), MagicMock())
        mock_stdio.return_value.__aexit__.return_value = None
        mock_session_cls.return_value.__aenter__.return_value = mock_session
        mock_session_cls.return_value.__aexit__.return_value = None

        result = await client.call_tool("k8s_get_pods", {"namespace": "default"})

        assert result.status == "success"
        assert result.content == "pod-1\npod-2"
        assert result.is_error is False


@pytest.mark.asyncio
async def test_call_tool_handles_error_status():
    client = ProcessUpstreamClient(
        command="k8s",
        upstream_type=UpstreamType.KUBERNETES,
    )

    mock_result = SimpleNamespace(
        content=[SimpleNamespace(text="pod not found")],
        is_error=True,
    )

    mock_session = AsyncMock()
    mock_session.call_tool.return_value = mock_result

    with (
        patch("homelab_mcp.infrastructure.upstream.client.stdio_client") as mock_stdio,
        patch("homelab_mcp.infrastructure.upstream.client.ClientSession") as mock_session_cls,
    ):
        mock_stdio.return_value.__aenter__.return_value = (MagicMock(), MagicMock())
        mock_stdio.return_value.__aexit__.return_value = None
        mock_session_cls.return_value.__aenter__.return_value = mock_session
        mock_session_cls.return_value.__aexit__.return_value = None

        result = await client.call_tool("k8s_get_pods", {"namespace": "nonexistent"})

        assert result.status == "error"
        assert result.content == "pod not found"
        assert result.is_error is True
