"""FastMCP client infrastructure adapter implementing MCPClientInterface."""

import contextlib
import logging
from typing import Any

import httpx
from fastmcp import Client
from langchain_core.tools import StructuredTool, ToolException
from lyoko.config import settings
from lyoko.domain.exceptions import (
    MCPAuthenticationError,
    MCPEndpointNotFoundError,
    MCPGatewayError,
    MCPGatewayUnreachableError,
)
from lyoko.domain.interfaces import MCPClientInterface

logger = logging.getLogger("lyoko.infrastructure.mcp.client")

_PROBE_TIMEOUT_SECONDS = 5.0
_PROBE_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}
_INITIALIZE_REQUEST = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-03-26",
        "capabilities": {},
        "clientInfo": {"name": "lyoko-connectivity-check", "version": "0"},
    },
}


def _root_cause(exc: BaseException) -> BaseException:
    """Unwrap (nested) exception groups raised by anyio task groups to the first leaf error."""
    while isinstance(exc, BaseExceptionGroup) and exc.exceptions:
        exc = exc.exceptions[0]
    return exc


class FastMCPClient(MCPClientInterface):
    def __init__(self, server_url: str | None = None, token: str | None = None):
        self.server_url = server_url or settings.mcp_server_url
        raw_token = token if token is not None else settings.service_token
        self.token = (
            raw_token.get_secret_value()
            if hasattr(raw_token, "get_secret_value")
            else str(raw_token)
            if raw_token
            else ""
        )

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def _error_for_status(self, status_code: int) -> MCPGatewayError | None:
        """Map the HTTP status returned by the gateway to a precise domain error."""
        if status_code < 400:
            return None
        if status_code in (401, 403):
            hint = (
                "Check that SERVICE_TOKEN matches the gateway's service token."
                if self.token
                else "No SERVICE_TOKEN is configured for LYOKO."
            )
            return MCPAuthenticationError(
                f"MCP gateway at {self.server_url} rejected the credentials "
                f"(HTTP {status_code}). {hint}"
            )
        if status_code == 404:
            return MCPEndpointNotFoundError(
                f"MCP gateway at {self.server_url} returned HTTP 404. MCP_SERVER_URL must "
                "point at the Streamable HTTP endpoint (usually ending in /mcp)."
            )
        return MCPGatewayError(f"MCP gateway at {self.server_url} returned HTTP {status_code}.")

    async def _probe(self) -> MCPGatewayError | None:
        """Send a raw MCP ``initialize`` request to learn the real HTTP status of the gateway.

        fastmcp collapses 401/403/500 into one generic error, so a plain HTTP request is the
        only reliable way to tell a wrong token from a wrong URL or a broken gateway.
        """
        headers = dict(_PROBE_HEADERS)
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        try:
            async with httpx.AsyncClient(
                timeout=_PROBE_TIMEOUT_SECONDS, follow_redirects=True
            ) as http:
                response = await http.post(
                    self.server_url, json=_INITIALIZE_REQUEST, headers=headers
                )
                session_id = response.headers.get("mcp-session-id")
                if response.status_code < 400 and session_id:
                    # Best-effort cleanup so the probe does not leave an idle session behind.
                    with contextlib.suppress(httpx.HTTPError):
                        await http.delete(
                            self.server_url, headers={**headers, "Mcp-Session-Id": session_id}
                        )
        except httpx.TransportError as exc:
            return MCPGatewayUnreachableError(
                f"MCP gateway at {self.server_url} is unreachable: {type(exc).__name__}: {exc}"
            )
        return self._error_for_status(response.status_code)

    async def _to_gateway_error(self, operation: str, exc: BaseException) -> MCPGatewayError:
        """Convert any failure into a domain error, enriched with the probed root cause."""
        if isinstance(exc, MCPGatewayError):
            return exc
        diagnosed = await self._probe()
        if diagnosed is not None:
            error = diagnosed
        else:
            cause = _root_cause(exc)
            error = MCPGatewayError(f"MCP gateway {operation} failed: {cause}")
        logger.error("MCP gateway %s failed: %s", operation, error)
        return error

    async def verify_connection(self) -> None:
        """Raise a typed domain error unless the gateway accepts our connection and credentials."""
        error = await self._probe()
        if error is not None:
            raise error
        logger.info("MCP gateway connectivity check passed (%s).", self.server_url)

    # ------------------------------------------------------------------
    # Gateway operations
    # ------------------------------------------------------------------

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        """Call a tool on homelab-mcp gateway, routing upstream tools through gateway_call_tool.

        Failures are returned as ``{"status": "failed", ...}`` so remediation workflows can
        branch on them without exception handling.
        """
        auth_token = self.token if self.token else None
        try:
            async with Client(self.server_url, auth=auth_token) as client:
                if name in [
                    "gateway_list_tools",
                    "gateway_list_categories",
                    "gateway_call_tool",
                    "telegram_send_message",
                    "telegram_send_alert",
                ]:
                    res = await client.call_tool(name, arguments)
                    return res.data
                else:
                    res = await client.call_tool(
                        "gateway_call_tool", {"tool_name": name, "arguments": arguments}
                    )
                    return res.data
        except Exception as exc:
            error = await self._to_gateway_error(f"tool call '{name}'", exc)
            return {"error": str(error), "status": "failed", "tool": name}

    async def list_categories(self) -> list[dict[str, Any]]:
        """List all connected upstream MCP categories and their available tool counts.

        Raises:
            MCPGatewayError: if the gateway cannot be used (never silently returns ``[]``).
        """
        auth_token = self.token if self.token else None
        try:
            async with Client(self.server_url, auth=auth_token) as client:
                res = await client.call_tool("gateway_list_categories", {})
                return res.data if isinstance(res.data, list) else []
        except Exception as exc:
            raise await self._to_gateway_error("list categories", exc) from exc

    async def list_tools(self, upstream: str | None = None) -> list[dict[str, Any]]:
        """List all tools available from gateway and connected upstreams, optionally filtered.

        Raises:
            MCPGatewayError: if the gateway cannot be used (never silently returns ``[]``).
        """
        auth_token = self.token if self.token else None
        try:
            async with Client(self.server_url, auth=auth_token) as client:
                args = {"upstream": upstream} if upstream else {}
                res = await client.call_tool("gateway_list_tools", args)
                return res.data if isinstance(res.data, list) else []
        except Exception as exc:
            raise await self._to_gateway_error("list tools", exc) from exc

    def get_langchain_tools(self) -> list[Any]:
        """Return LangChain StructuredTool instances to dynamically discover and execute homelab tools.

        Gateway failures are raised as ``ToolException`` so the LLM receives the real error
        message (and the trace records a failed tool call) instead of an empty result it
        could mistake for "nothing is available" and answer from imagination.
        """

        async def _gateway_list_categories() -> str:
            """Discover all active connected upstream categories and how many tools each provides."""
            try:
                categories = await self.list_categories()
                if not categories:
                    # Fallback to computing from list_tools
                    tools = await self.list_tools()
                    counts: dict[str, int] = {}
                    for t in tools:
                        k = str(t.get("upstream", "other"))
                        counts[k] = counts.get(k, 0) + 1
                    categories = [
                        {"upstream": k, "tool_count": v} for k, v in sorted(counts.items())
                    ]
            except MCPGatewayError as exc:
                raise ToolException(str(exc)) from exc
            return str(categories)

        async def _gateway_list_tools(upstream: str | None = None) -> str:
            """List operational tools available in the homelab infrastructure, optionally filtered by upstream category.

            Args:
                upstream: Optional upstream category name to filter (e.g. 'homeassistant', 'unifi', 'kubernetes', 'grafana', 'github').
            """
            try:
                tools = await self.list_tools(upstream=upstream)
            except MCPGatewayError as exc:
                raise ToolException(str(exc)) from exc
            return str(
                [
                    {
                        "name": t.get("name"),
                        "description": t.get("description"),
                        "upstream": t.get("upstream"),
                    }
                    for t in tools
                ]
            )

        async def _gateway_call_tool(tool_name: str, arguments: dict[str, Any]) -> str:
            """Execute any operational homelab tool by its exact name with arguments.

            Args:
                tool_name: Exact name of the tool to invoke.
                arguments: Dictionary of parameters matching the tool schema.
            """
            result = await self.call_tool(tool_name, arguments)
            if isinstance(result, dict) and result.get("status") == "failed":
                raise ToolException(str(result.get("error", "unknown MCP gateway error")))
            return str(result)

        categories_tool = StructuredTool.from_function(
            coroutine=_gateway_list_categories,
            name="gateway_list_categories",
            description="Discover which upstream services and categories are currently connected and available in the homelab environment (e.g. smart home, network controllers, clusters, metrics).",
            handle_tool_error=True,
        )

        list_tool = StructuredTool.from_function(
            coroutine=_gateway_list_tools,
            name="gateway_list_tools",
            description="List specific operational tools available in the homelab, with optional 'upstream' category filter to quickly find relevant tools without loading the entire catalog.",
            handle_tool_error=True,
        )

        call_tool = StructuredTool.from_function(
            coroutine=_gateway_call_tool,
            name="gateway_call_tool",
            description="Execute any operational homelab tool by name with arguments to fetch live status, manage devices, query metrics, or perform operations.",
            handle_tool_error=True,
        )

        return [categories_tool, list_tool, call_tool]
