"""Tests for FastMCPClient failure diagnosis and the startup gateway check."""

import http.server
import socketserver
import threading
from collections.abc import Iterator
from unittest.mock import AsyncMock, patch

import pytest
from lyoko.domain.exceptions import (
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
