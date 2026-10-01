"""Unit tests for ProcessUpstreamClient stdio parameter construction."""

from homelab_mcp.domain.models import UpstreamType
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
