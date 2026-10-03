"""FastMCP client infrastructure adapter implementing MCPClientInterface."""

import contextlib
import logging
import re
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
from pydantic import create_model

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
# Domains larger than this keep domain-scoped discovery instead of binding every tool.
_MAX_BOUND_DOMAIN_TOOLS = 40
_JSON_TYPE_MAP = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
    "object": dict,
    "array": list,
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
                    "gateway_get_domain_tools",
                    "gateway_get_tool_schema",
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

    async def list_tools(
        self,
        upstream: str | None = None,
        query: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """List tools available from the gateway, optionally filtered by upstream or keyword.

        Raises:
            MCPGatewayError: if the gateway cannot be used (never silently returns ``[]``).
        """
        auth_token = self.token if self.token else None
        try:
            async with Client(self.server_url, auth=auth_token) as client:
                args: dict[str, Any] = {}
                if upstream:
                    args["upstream"] = upstream
                if query:
                    args["query"] = query
                if limit:
                    args["limit"] = limit
                res = await client.call_tool("gateway_list_tools", args)
                return res.data if isinstance(res.data, list) else []
        except Exception as exc:
            raise await self._to_gateway_error("list tools", exc) from exc

    async def get_tool_schema(self, tool_name: str) -> Any:
        """Return the full parameter schema of a gateway tool.

        Raises:
            MCPGatewayError: if the gateway cannot be used.
        """
        auth_token = self.token if self.token else None
        try:
            async with Client(self.server_url, auth=auth_token) as client:
                res = await client.call_tool("gateway_get_tool_schema", {"tool_name": tool_name})
                return res.data
        except Exception as exc:
            raise await self._to_gateway_error(f"get schema of '{tool_name}'", exc) from exc

    async def get_domain_tool_definitions(self, domain: str) -> list[dict[str, Any]]:
        """Fetch the full tool catalog for one upstream domain from the gateway."""
        auth_token = self.token if self.token else None
        try:
            async with Client(self.server_url, auth=auth_token) as client:
                res = await client.call_tool("gateway_get_domain_tools", {"domain": domain})
                data = res.data
        except Exception as exc:
            raise await self._to_gateway_error(f"list domain tools for '{domain}'", exc) from exc

        if isinstance(data, dict) and data.get("error"):
            raise MCPGatewayError(str(data["error"]))
        if not isinstance(data, list):
            return []
        if data and isinstance(data[0], dict) and data[0].get("error"):
            raise MCPGatewayError(str(data[0]["error"]))
        return [t for t in data if isinstance(t, dict) and t.get("name")]

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
            if isinstance(result, dict) and result.get("status") == "failed":
                raise ToolException(str(result.get("error", "unknown MCP gateway error")))
            return str(result)

        return _run

    def _bind_domain_tool(
        self,
        definition: dict[str, Any],
        authorizer: ToolAuthorizer | None,
    ) -> Any:
        """Bind one upstream tool as a direct LangChain StructuredTool."""
        tool_name = str(definition["name"])
        description = (definition.get("description") or tool_name).strip()
        parameters = definition.get("parameters") or {}
        args_schema = _args_schema_for_tool(tool_name, parameters)
        run = self._authorized_call(tool_name, authorizer)

        async def _invoke(**kwargs: Any) -> str:
            arguments = {key: value for key, value in kwargs.items() if value is not None}
            if "arguments" in arguments and len(arguments) == 1:
                nested = arguments["arguments"]
                if isinstance(nested, dict):
                    arguments = nested
            return await RunnableLambda(run, name=f"mcp:{tool_name}").ainvoke(arguments)

        return StructuredTool.from_function(
            coroutine=_invoke,
            name=tool_name,
            description=description,
            args_schema=args_schema,
            handle_tool_error=True,
        )

    def _domain_discovery_tools(
        self,
        domain: str,
        authorizer: ToolAuthorizer | None,
    ) -> list[Any]:
        """Fallback toolset for large domains: search and call stay locked to ``domain``."""

        async def _list_tools(query: str | None = None, limit: int = 25) -> str:
            try:
                tools = await self.list_tools(upstream=domain, query=query, limit=limit)
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
                coroutine=_list_tools,
                name="gateway_list_tools",
                description=(
                    f"List tools in the '{domain}' domain only. Pass a keyword query to narrow "
                    "results. Do not invent tools outside this list."
                ),
                handle_tool_error=True,
            ),
            StructuredTool.from_function(
                coroutine=_get_schema,
                name="gateway_get_tool_schema",
                description="Get the parameter schema of one tool from this domain before calling it.",
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
        """Return LangChain tools scoped to one upstream domain for a specialist agent."""
        try:
            definitions = await self.get_domain_tool_definitions(domain)
        except MCPGatewayError as exc:
            raise ToolException(str(exc)) from exc

        if len(definitions) > _MAX_BOUND_DOMAIN_TOOLS:
            logger.info(
                "Domain '%s' has %s tools; using scoped discovery instead of full binding.",
                domain,
                len(definitions),
            )
            return self._domain_discovery_tools(domain, authorizer)

        return [self._bind_domain_tool(defn, authorizer) for defn in definitions]

    def get_langchain_tools(self, authorizer: ToolAuthorizer | None = None) -> list[Any]:
        """Return LangChain StructuredTool instances to dynamically discover and execute homelab tools.

        Gateway failures are raised as ``ToolException`` so the LLM receives the real error
        message (and the trace records a failed tool call) instead of an empty result it
        could mistake for "nothing is available" and answer from imagination.

        When ``authorizer`` is given it is consulted before every ``gateway_call_tool``
        invocation; a refusal is raised as a ``ToolException`` and the tool never runs.
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

        async def _gateway_list_tools(
            upstream: str | None = None, query: str | None = None, limit: int = 25
        ) -> str:
            """List operational tools available in the homelab, optionally filtered.

            Args:
                upstream: Optional upstream category to filter (e.g. 'homeassistant', 'unifi', 'kubernetes', 'grafana', 'github').
                query: Optional keyword matched against tool names and descriptions (e.g. 'pod', 'restart', 'client').
                limit: Maximum number of tools to return (default 25, max 50).
            """
            try:
                tools = await self.list_tools(upstream=upstream, query=query, limit=limit)
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

            async def _run(call_arguments: dict[str, Any]) -> str:
                if authorizer is not None:
                    refusal = await authorizer(tool_name, call_arguments)
                    if refusal:
                        raise ToolException(refusal)
                result = await self.call_tool(tool_name, call_arguments)
                if isinstance(result, dict) and result.get("status") == "failed":
                    raise ToolException(str(result.get("error", "unknown MCP gateway error")))
                return str(result)

            # Every call goes through one generic tool, so name the nested run after the real
            # gateway tool. Traces then show ``mcp:pods_log`` instead of an anonymous call.
            return await RunnableLambda(_run, name=f"mcp:{tool_name}").ainvoke(arguments)

        categories_tool = StructuredTool.from_function(
            coroutine=_gateway_list_categories,
            name="gateway_list_categories",
            description="Discover which upstream services and categories are currently connected and available in the homelab environment (e.g. smart home, network controllers, clusters, metrics).",
            handle_tool_error=True,
        )

        list_tool = StructuredTool.from_function(
            coroutine=_gateway_list_tools,
            name="gateway_list_tools",
            description="List operational tools available in the homelab. Filter with 'upstream' (category) and 'query' (keyword) to find relevant tools without loading the entire catalog.",
            handle_tool_error=True,
        )

        call_tool = StructuredTool.from_function(
            coroutine=_gateway_call_tool,
            name="gateway_call_tool",
            description="Execute any operational homelab tool by name with arguments to fetch live status, manage devices, query metrics, or perform operations.",
            handle_tool_error=True,
        )

        schema_tool = StructuredTool.from_function(
            coroutine=_gateway_get_tool_schema,
            name="gateway_get_tool_schema",
            description="Get the exact parameter schema of a specific tool before calling it with gateway_call_tool.",
            handle_tool_error=True,
        )

        return [categories_tool, list_tool, schema_tool, call_tool]


def _safe_model_name(tool_name: str) -> str:
    cleaned = re.sub(r"[^0-9a-zA-Z_]", "_", tool_name)
    if cleaned and cleaned[0].isdigit():
        cleaned = f"T_{cleaned}"
    return cleaned or "Tool"


def _args_schema_for_tool(tool_name: str, parameters: dict[str, Any]) -> type:
    """Build a Pydantic args model from an MCP JSON Schema ``parameters`` object."""
    properties = parameters.get("properties") if isinstance(parameters, dict) else None
    if not isinstance(properties, dict) or not properties:
        return create_model(
            f"{_safe_model_name(tool_name)}Args",
            arguments=(dict[str, Any], {}),
        )

    required = set(parameters.get("required") or [])
    fields: dict[str, Any] = {}
    for key, prop in properties.items():
        json_type = prop.get("type") if isinstance(prop, dict) else None
        annotation: Any = _JSON_TYPE_MAP.get(json_type, Any) if isinstance(json_type, str) else Any
        if key in required:
            fields[key] = (annotation, ...)
        else:
            fields[key] = (annotation | None, None)
    return create_model(f"{_safe_model_name(tool_name)}Args", **fields)
