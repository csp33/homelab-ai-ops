"""FastMCP client infrastructure adapter implementing MCPClientInterface."""

import contextlib
import logging
from typing import Any

import httpx
from fastmcp import Client
from langchain_core.runnables import RunnableLambda
from langchain_core.tools import StructuredTool, ToolException
from lyoko.config import settings
from lyoko.domain.exceptions.mcp import (
    MCPAuthenticationError,
    MCPEndpointNotFoundError,
    MCPGatewayError,
    MCPGatewayUnreachableError,
)
from lyoko.domain.interfaces.mcp import MCPClientInterface, ToolAuthorizer

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
# Gateway meta-tools are called directly; every upstream tool is routed via gateway_call_tool.
_GATEWAY_META_TOOLS = (
    "gateway_get_domain_tools",
    "gateway_get_tool_schema",
    "gateway_call_tool",
)
# Domain catalog paging: the gateway caps a page at 100 entries; cap the full fetch too.
_DOMAIN_PAGE_SIZE = 100
_MAX_DOMAIN_PAGES = 20
# Hard ceiling for a single gateway tool call: a dropped Streamable HTTP session would otherwise
# leave the client waiting forever for a reply that never arrives and hang the agent request.
_CALL_TIMEOUT_SECONDS = 60.0


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
        """Call a tool on sector5-mcp gateway, routing upstream tools through gateway_call_tool.

        Failures are returned as ``{"status": "failed", ...}`` so remediation workflows can
        branch on them without exception handling.
        """
        auth_token = self.token if self.token else None
        try:
            async with Client(self.server_url, auth=auth_token) as client:
                if name in _GATEWAY_META_TOOLS:
                    res = await client.call_tool(name, arguments, timeout=_CALL_TIMEOUT_SECONDS)
                else:
                    res = await client.call_tool(
                        "gateway_call_tool",
                        {"tool_name": name, "arguments": arguments},
                        timeout=_CALL_TIMEOUT_SECONDS,
                    )
                return res.data
        except Exception as exc:
            error = await self._to_gateway_error(f"tool call '{name}'", exc)
            return {"error": str(error), "status": "failed", "tool": name}

    async def get_domain_tools_page(
        self,
        domain: str,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Fetch one page of a domain's tool index from the gateway.

        Returns the gateway payload: ``domain``, ``total``, ``limit``, ``offset``, ``has_more``
        and ``tools`` (index entries: name, description, upstream, parameters/schema).

        Raises:
            MCPGatewayError: if the gateway cannot be used or reports the domain has no tools,
                so a broken gateway is never mistaken for an empty domain.
        """
        auth_token = self.token if self.token else None
        try:
            async with Client(self.server_url, auth=auth_token) as client:
                res = await client.call_tool(
                    "gateway_get_domain_tools",
                    {"domain": domain, "limit": limit, "offset": offset},
                    timeout=_CALL_TIMEOUT_SECONDS,
                )
                data = res.data
        except Exception as exc:
            raise await self._to_gateway_error(f"list domain tools for '{domain}'", exc) from exc

        if isinstance(data, dict) and data.get("error"):
            raise MCPGatewayError(str(data["error"]))
        if not isinstance(data, dict):
            return {
                "domain": domain,
                "total": 0,
                "limit": limit,
                "offset": offset,
                "has_more": False,
                "tools": [],
            }
        raw_tools = data.get("tools") or []
        tools = [t for t in raw_tools if isinstance(t, dict) and t.get("name")]
        return {**data, "tools": tools}

    async def get_domain_catalog(
        self,
        domain: str,
        page_size: int = _DOMAIN_PAGE_SIZE,
    ) -> list[dict[str, Any]]:
        """Fetch the full tool index for one upstream domain, following pagination.

        Used to inject a domain's tool list, with each tool's exact argument names, into a
        specialist prompt. Raises on gateway failure instead of returning an empty list, so a
        broken gateway is never mistaken for an empty domain.
        """
        tools: list[dict[str, Any]] = []
        offset = 0
        for _ in range(_MAX_DOMAIN_PAGES):
            page = await self.get_domain_tools_page(domain, limit=page_size, offset=offset)
            page_tools = page.get("tools") or []
            tools.extend(page_tools)
            if not page.get("has_more") or not page_tools:
                break
            offset = int(page.get("offset", offset)) + len(page_tools)
        return tools

    async def get_tool_schema(self, tool_name: str) -> Any:
        """Return the full parameter schema of a gateway tool.

        Raises:
            MCPGatewayError: if the gateway cannot be used.
        """
        auth_token = self.token if self.token else None
        try:
            async with Client(self.server_url, auth=auth_token) as client:
                res = await client.call_tool(
                    "gateway_get_tool_schema",
                    {"tool_name": tool_name},
                    timeout=_CALL_TIMEOUT_SECONDS,
                )
                return res.data
        except Exception as exc:
            raise await self._to_gateway_error(f"get schema of '{tool_name}'", exc) from exc

    def _authorized_call(
        self,
        tool_name: str,
        authorizer: ToolAuthorizer | None,
    ):
        async def _run(arguments: dict[str, Any]) -> str:
            if authorizer is not None:
                refusal = await authorizer(tool_name, arguments)
                if refusal:
                    raise ToolException(refusal)
            result = await self.call_tool(tool_name, arguments)
            if isinstance(result, dict):
                if result.get("status") == "failed":
                    raise ToolException(str(result.get("error", "unknown MCP gateway error")))
                if result.get("status") == "success":
                    content = result.get("content")
                    if content is None or content == "" or content == [] or content == {}:
                        result = dict(result)
                        result["content"] = "No resources found or empty result."
            elif result is None or result == "":
                result = "No resources found or empty result."
            return str(result)

        return _run

    def _domain_discovery_tools(
        self,
        domain: str,
        authorizer: ToolAuthorizer | None,
    ) -> list[Any]:
        """Domain-locked trio: discover the domain catalog, read a schema, execute a tool."""

        async def _list_domain_tools(limit: int = 50, offset: int = 0) -> str:
            try:
                return str(await self.get_domain_tools_page(domain, limit=limit, offset=offset))
            except MCPGatewayError as exc:
                raise ToolException(str(exc)) from exc

        async def _get_schema(tool_name: str) -> str:
            try:
                return str(await self.get_tool_schema(tool_name))
            except MCPGatewayError as exc:
                raise ToolException(str(exc)) from exc

        async def _call_tool(tool_name: str, arguments: dict[str, Any]) -> str:
            return await RunnableLambda(
                self._authorized_call(tool_name, authorizer),
                name=f"mcp:{tool_name}",
            ).ainvoke(arguments)

        return [
            StructuredTool.from_function(
                coroutine=_list_domain_tools,
                name="gateway_get_domain_tools",
                description=(
                    f"List the tools of the '{domain}' domain with a one-line description. "
                    "Paginate with 'limit' (max 100) and 'offset'; follow 'has_more'. Call this to "
                    "discover what you can do, then gateway_get_tool_schema for the arguments and "
                    "gateway_call_tool to run it. Do not invent tools outside this list."
                ),
                handle_tool_error=True,
            ),
            StructuredTool.from_function(
                coroutine=_get_schema,
                name="gateway_get_tool_schema",
                description=(f"Get the parameter schema of one '{domain}' tool before calling it."),
                handle_tool_error=True,
            ),
            StructuredTool.from_function(
                coroutine=_call_tool,
                name="gateway_call_tool",
                description=f"Execute a '{domain}' domain tool by exact name with arguments.",
                handle_tool_error=True,
            ),
        ]

    async def get_domain_langchain_tools(
        self,
        domain: str,
        authorizer: ToolAuthorizer | None = None,
    ) -> list[Any]:
        """Return the domain-locked discovery trio for a specialist agent.

        The specialist discovers its own domain catalog (which already carries each tool's
        argument schema), reads a schema when a call is rejected, and executes through the single
        guarded ``gateway_call_tool``. It can never reach another upstream.
        """
        return self._domain_discovery_tools(domain, authorizer)

    def get_langchain_tools(self, authorizer: ToolAuthorizer | None = None) -> list[Any]:
        """Return LangChain tools to discover and execute homelab tools across domains.

        The surface is deliberately three tools: discover a domain's index, read one tool's
        schema, execute it. Gateway failures are raised as ``ToolException`` so the LLM sees the
        real error instead of an empty result it could mistake for "nothing is available".

        When ``authorizer`` is given it is consulted before every ``gateway_call_tool``
        invocation; a refusal is raised as a ``ToolException`` and the tool never runs.
        """

        async def _gateway_get_domain_tools(domain: str, limit: int = 50, offset: int = 0) -> str:
            """List one page of the tools of one upstream domain.

            Args:
                domain: Upstream domain, e.g. 'kubernetes', 'unifi', 'homeassistant', 'grafana', 'github', 'telegram'.
                limit: Maximum tools to return in this page (max 100).
                offset: Number of tools to skip for pagination.
            """
            try:
                return str(await self.get_domain_tools_page(domain, limit=limit, offset=offset))
            except MCPGatewayError as exc:
                raise ToolException(str(exc)) from exc

        async def _gateway_get_tool_schema(tool_name: str) -> str:
            """Get the full parameter schema and description of one tool.

            Args:
                tool_name: Exact name of the tool to inspect.
            """
            try:
                return str(await self.get_tool_schema(tool_name))
            except MCPGatewayError as exc:
                raise ToolException(str(exc)) from exc

        async def _gateway_call_tool(tool_name: str, arguments: dict[str, Any]) -> str:
            """Execute any operational homelab tool by its exact name with arguments.

            Args:
                tool_name: Exact name of the tool to invoke.
                arguments: Dictionary of parameters matching the tool schema.
            """
            # Every call goes through one generic tool, so name the nested run after the real
            # gateway tool. Traces then show ``mcp:pods_log`` instead of an anonymous call.
            return await RunnableLambda(
                self._authorized_call(tool_name, authorizer),
                name=f"mcp:{tool_name}",
            ).ainvoke(arguments)

        domain_tool = StructuredTool.from_function(
            coroutine=_gateway_get_domain_tools,
            name="gateway_get_domain_tools",
            description=(
                "List the tools available in one upstream domain (kubernetes, unifi, "
                "homeassistant, grafana, github, telegram). Use it to discover capabilities, "
                "then gateway_get_tool_schema and gateway_call_tool."
            ),
            handle_tool_error=True,
        )

        schema_tool = StructuredTool.from_function(
            coroutine=_gateway_get_tool_schema,
            name="gateway_get_tool_schema",
            description="Get the exact parameter schema of a specific tool before calling it with gateway_call_tool.",
            handle_tool_error=True,
        )

        call_tool = StructuredTool.from_function(
            coroutine=_gateway_call_tool,
            name="gateway_call_tool",
            description="Execute any operational homelab tool by name with arguments to fetch live status, manage devices, query metrics, or perform operations.",
            handle_tool_error=True,
        )

        return [domain_tool, schema_tool, call_tool]
