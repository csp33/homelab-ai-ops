"""Tests for FastMCPClient failure diagnosis and the startup gateway check."""

import http.server
import socketserver
import threading
from collections.abc import Iterator
from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.callbacks import BaseCallbackHandler
from lyoko.domain.exceptions.mcp import (
    MCPAuthenticationError,
    MCPEndpointNotFoundError,
    MCPGatewayError,
    MCPGatewayUnreachableError,
)
from lyoko.infrastructure.mcp.client import FastMCPClient
from lyoko.main import verify_mcp_gateway

SECRET_TOKEN = "super-secret-service-token"


class _StatusServer:
    """Tiny HTTP server answering every request with a fixed status code."""

    def __init__(self, status_code: int) -> None:
        status = status_code

        class Handler(http.server.BaseHTTPRequestHandler):
            def _respond(self) -> None:
                self.send_response(status)
                self.send_header("Content-Length", "0")
                self.end_headers()

            do_POST = _respond
            do_DELETE = _respond
            do_GET = _respond

            def log_message(self, *args: object) -> None:
                pass

        self._server = socketserver.TCPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self._server.server_address[1]}/mcp"
        threading.Thread(target=self._server.serve_forever, daemon=True).start()

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()


@pytest.fixture
def status_server() -> Iterator[type[_StatusServer]]:
    servers: list[_StatusServer] = []

    def factory(status_code: int) -> _StatusServer:
        server = _StatusServer(status_code)
        servers.append(server)
        return server

    yield factory  # type: ignore[misc]
    for server in servers:
        server.close()


@pytest.mark.asyncio
async def test_verify_connection_passes_on_success(status_server):
    server = status_server(200)
    await FastMCPClient(server_url=server.url, token=SECRET_TOKEN).verify_connection()


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [401, 403])
async def test_verify_connection_reports_missing_token(status_server, status_code):
    server = status_server(status_code)
    with pytest.raises(MCPAuthenticationError, match="No SERVICE_TOKEN is configured"):
        await FastMCPClient(server_url=server.url, token="").verify_connection()


@pytest.mark.asyncio
async def test_verify_connection_reports_wrong_token_without_leaking_it(status_server):
    server = status_server(401)
    with pytest.raises(MCPAuthenticationError) as exc_info:
        await FastMCPClient(server_url=server.url, token=SECRET_TOKEN).verify_connection()
    assert "matches the gateway's service token" in str(exc_info.value)
    assert SECRET_TOKEN not in str(exc_info.value)


@pytest.mark.asyncio
async def test_verify_connection_reports_wrong_path(status_server):
    server = status_server(404)
    with pytest.raises(MCPEndpointNotFoundError, match="/mcp"):
        await FastMCPClient(server_url=server.url, token=SECRET_TOKEN).verify_connection()


@pytest.mark.asyncio
async def test_verify_connection_reports_unreachable_gateway():
    client = FastMCPClient(server_url="http://127.0.0.1:1/mcp", token=SECRET_TOKEN)
    with pytest.raises(MCPGatewayUnreachableError):
        await client.verify_connection()


@pytest.mark.asyncio
async def test_verify_connection_reports_other_http_errors(status_server):
    server = status_server(500)
    with pytest.raises(MCPGatewayError, match="HTTP 500") as exc_info:
        await FastMCPClient(server_url=server.url, token=SECRET_TOKEN).verify_connection()
    assert not exc_info.value.is_configuration_error


@pytest.mark.asyncio
async def test_list_tools_raises_instead_of_returning_empty_list(status_server):
    """Regression: a 401 used to be logged as a warning and swallowed as `[]`."""
    server = status_server(401)
    client = FastMCPClient(server_url=server.url, token="")
    with pytest.raises(MCPAuthenticationError):
        await client.list_tools()
    with pytest.raises(MCPAuthenticationError):
        await client.list_categories()


@pytest.mark.asyncio
async def test_call_tool_returns_actionable_failure(status_server):
    server = status_server(404)
    client = FastMCPClient(server_url=server.url, token=SECRET_TOKEN)
    result = await client.call_tool("k8s_get_pods", {"namespace": "default"})
    assert result["status"] == "failed"
    assert result["tool"] == "k8s_get_pods"
    assert "MCP_SERVER_URL" in result["error"]
    assert SECRET_TOKEN not in result["error"]


@pytest.mark.asyncio
async def test_langchain_tools_surface_gateway_error_to_the_llm(status_server):
    """The LLM must see the real cause so it can tell the user instead of guessing."""
    server = status_server(401)
    client = FastMCPClient(server_url=server.url, token="")
    tools = {t.name: t for t in client.get_langchain_tools()}

    for name, args in [
        ("gateway_list_categories", {}),
        ("gateway_list_tools", {}),
        ("gateway_call_tool", {"tool_name": "k8s_get_pods", "arguments": {}}),
    ]:
        output = await tools[name].ainvoke(args)
        assert "rejected the credentials" in output, name


@pytest.mark.asyncio
async def test_startup_check_aborts_on_configuration_error():
    client = AsyncMock()
    client.verify_connection.side_effect = MCPAuthenticationError("bad token")
    with patch("lyoko.main.settings.mcp_fail_fast", True), pytest.raises(MCPAuthenticationError):
        await verify_mcp_gateway(client)


@pytest.mark.asyncio
async def test_startup_check_tolerates_configuration_error_when_fail_fast_disabled():
    client = AsyncMock()
    client.verify_connection.side_effect = MCPEndpointNotFoundError("wrong path")
    with patch("lyoko.main.settings.mcp_fail_fast", False):
        await verify_mcp_gateway(client)


@pytest.mark.asyncio
async def test_startup_check_tolerates_unreachable_gateway():
    client = AsyncMock()
    client.verify_connection.side_effect = MCPGatewayUnreachableError("still starting")
    with patch("lyoko.main.settings.mcp_fail_fast", True):
        await verify_mcp_gateway(client)


@pytest.mark.asyncio
async def test_langchain_tools_expose_search_and_schema_discovery():
    tools = {t.name: t for t in FastMCPClient(server_url="http://x/mcp").get_langchain_tools()}

    assert set(tools) == {
        "gateway_list_categories",
        "gateway_list_tools",
        "gateway_get_tool_schema",
        "gateway_call_tool",
    }
    assert {"upstream", "query", "limit"} <= set(tools["gateway_list_tools"].args)


@pytest.mark.asyncio
async def test_authorizer_refusal_blocks_the_call_and_reaches_the_llm():
    client = FastMCPClient(server_url="http://x/mcp", token="")
    client.call_tool = AsyncMock(return_value={"ok": True})
    authorizer = AsyncMock(return_value="Refused: not allowed")
    tools = {t.name: t for t in client.get_langchain_tools(authorizer=authorizer)}

    output = await tools["gateway_call_tool"].ainvoke(
        {"tool_name": "pods_delete", "arguments": {"name": "x"}}
    )

    assert output == "Refused: not allowed"
    authorizer.assert_awaited_once_with("pods_delete", {"name": "x"})
    client.call_tool.assert_not_called()


@pytest.mark.asyncio
async def test_authorizer_allowing_the_call_lets_it_through():
    client = FastMCPClient(server_url="http://x/mcp", token="")
    client.call_tool = AsyncMock(return_value={"ok": True})
    authorizer = AsyncMock(return_value=None)
    tools = {t.name: t for t in client.get_langchain_tools(authorizer=authorizer)}

    output = await tools["gateway_call_tool"].ainvoke(
        {"tool_name": "pods_get", "arguments": {"name": "x"}}
    )

    assert output == "{'ok': True}"
    client.call_tool.assert_awaited_once_with("pods_get", {"name": "x"})


@pytest.mark.asyncio
async def test_discovery_tools_are_never_gated():
    client = FastMCPClient(server_url="http://x/mcp", token="")
    client.list_categories = AsyncMock(return_value=[{"upstream": "kubernetes", "tool_count": 20}])
    authorizer = AsyncMock(return_value="Refused")
    tools = {t.name: t for t in client.get_langchain_tools(authorizer=authorizer)}

    output = await tools["gateway_list_categories"].ainvoke({})

    assert "kubernetes" in output
    authorizer.assert_not_called()


class _RunRecorder(BaseCallbackHandler):
    """Records every chain run (name, id, parent) the way a tracing backend would see it."""

    def __init__(self) -> None:
        self.runs: list[tuple[str, object, object]] = []
        self.tool_runs: list[tuple[str, object]] = []

    def on_chain_start(self, serialized, inputs, *, run_id, parent_run_id=None, name=None, **kw):
        self.runs.append((name or "", run_id, parent_run_id))

    def on_tool_start(self, serialized, input_str, *, run_id, **kwargs):
        self.tool_runs.append((serialized.get("name", ""), run_id))


@pytest.mark.asyncio
async def test_gateway_call_is_traced_under_the_name_of_the_real_tool():
    """Traces must say `mcp:pods_log`, not just `gateway_call_tool`, to be readable."""
    client = FastMCPClient(server_url="http://x/mcp", token="")
    client.call_tool = AsyncMock(return_value={"ok": True})
    tools = {t.name: t for t in client.get_langchain_tools()}
    recorder = _RunRecorder()

    await tools["gateway_call_tool"].ainvoke(
        {"tool_name": "pods_log", "arguments": {"name": "radarr"}},
        config={"callbacks": [recorder]},
    )

    ((tool_name, tool_run_id),) = recorder.tool_runs
    assert tool_name == "gateway_call_tool"
    ((span_name, _, parent),) = [r for r in recorder.runs if r[0].startswith("mcp:")]
    assert span_name == "mcp:pods_log"
    assert parent == tool_run_id


@pytest.mark.asyncio
async def test_refused_gateway_call_is_still_traced_under_the_tool_name():
    client = FastMCPClient(server_url="http://x/mcp", token="")
    client.call_tool = AsyncMock()
    authorizer = AsyncMock(return_value="Refused: read-only phase")
    tools = {t.name: t for t in client.get_langchain_tools(authorizer=authorizer)}
    recorder = _RunRecorder()

    output = await tools["gateway_call_tool"].ainvoke(
        {"tool_name": "pods_delete", "arguments": {"name": "x"}},
        config={"callbacks": [recorder]},
    )

    assert output == "Refused: read-only phase"
    assert "mcp:pods_delete" in [r[0] for r in recorder.runs]
    client.call_tool.assert_not_called()
