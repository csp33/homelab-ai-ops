"""Process-based upstream MCP client using official MCP SDK."""

import os
from typing import Any

from homelab_mcp.domain.interfaces import UpstreamMCPInterface
from homelab_mcp.domain.models import ToolDefinition, ToolResult, UpstreamType
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


class ProcessUpstreamClient(UpstreamMCPInterface):
    """Client that communicates with an upstream MCP server running as a sub-process over stdio."""

    def __init__(
        self,
        command: str,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
        upstream_type: UpstreamType | str = "unknown",
    ):
        self.command = command
        self.args = args or []
        self.env = {**os.environ, **(env or {})}
        self.upstream_type = upstream_type

    def _get_server_params(self) -> StdioServerParameters:
        return StdioServerParameters(
            command=self.command,
            args=self.args,
            env=self.env,
        )

    async def list_tools(self) -> list[ToolDefinition]:
        """Connect to upstream MCP server, initialize session, and discover tools."""
        server_params = self._get_server_params()
        async with (
            stdio_client(server_params) as (read, write),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            result = await session.list_tools()

            tool_definitions = []
            for tool in result.tools:
                parameters = getattr(tool, "input_schema", None)
                if parameters is None:
                    parameters = getattr(tool, "inputSchema", {})
                tool_definitions.append(
                    ToolDefinition(
                        name=tool.name,
                        description=tool.description or "",
                        parameters=parameters,
                        upstream_type=self.upstream_type,
                    )
                )
            return tool_definitions

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        """Connect to upstream MCP server and execute a specific tool."""
        server_params = self._get_server_params()
        async with (
            stdio_client(server_params) as (read, write),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            result = await session.call_tool(name, arguments)

            # Format content
            contents = []
            for item in result.content:
                if hasattr(item, "text"):
                    contents.append(item.text)
                else:
                    contents.append(str(item))

            is_error = getattr(result, "is_error", None)
            if is_error is None:
                is_error = getattr(result, "isError", False)
            return ToolResult(
                status="error" if is_error else "success",
                content="\n".join(contents)
                if len(contents) > 1
                else (contents[0] if contents else None),
                is_error=bool(is_error),
            )
