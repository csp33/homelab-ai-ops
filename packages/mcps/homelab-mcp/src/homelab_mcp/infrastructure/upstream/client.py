"""Process-based upstream MCP client using official MCP SDK with persistent sessions."""

import asyncio
import logging
import os
from contextlib import AsyncExitStack
from typing import Any

from homelab_mcp.domain.interfaces import UpstreamMCPInterface
from homelab_mcp.domain.models import ToolDefinition, ToolResult, UpstreamType
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

logger = logging.getLogger("homelab_mcp.upstream_client")


class ProcessUpstreamClient(UpstreamMCPInterface):
    """Client that communicates with an upstream MCP server via a persistent stdio sub-process."""

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
        self._lock = asyncio.Lock()
        self._session: ClientSession | None = None
        self._exit_stack: AsyncExitStack | None = None

    def _get_server_params(self) -> StdioServerParameters:
        return StdioServerParameters(
            command=self.command,
            args=self.args,
            env=self.env,
        )

    async def _ensure_connected(self) -> ClientSession:
        """Establish and initialize the persistent upstream process session if not already connected."""
        if self._session is not None:
            return self._session

        logger.info(f"Starting persistent upstream MCP process for '{self.upstream_type}' ({self.command})...")
        server_params = self._get_server_params()
        self._exit_stack = AsyncExitStack()
        try:
            read, write = await self._exit_stack.enter_async_context(stdio_client(server_params))
            session = await self._exit_stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
            self._session = session
            logger.info(f"Persistent upstream MCP session established for '{self.upstream_type}'.")
            return self._session
        except Exception as exc:
            logger.error(f"Failed to start upstream MCP process '{self.upstream_type}': {exc}")
            await self._close_session()
            raise

    async def _close_session(self) -> None:
        """Gracefully terminate upstream session and process."""
        if self._exit_stack:
            try:
                await self._exit_stack.aclose()
            except Exception as exc:
                logger.warning(f"Error terminating upstream MCP process for '{self.upstream_type}': {exc}")
            finally:
                self._session = None
                self._exit_stack = None

    async def list_tools(self) -> list[ToolDefinition]:
        """Discover tools using the persistent upstream session."""
        async with self._lock:
            try:
                session = await self._ensure_connected()
                result = await session.list_tools()
            except Exception as exc:
                logger.warning(
                    f"list_tools failed on upstream '{self.upstream_type}', attempting reconnection: {exc}"
                )
                await self._close_session()
                session = await self._ensure_connected()
                result = await session.list_tools()

            tool_definitions = []
            for tool in result.tools:
                tool_definitions.append(
                    ToolDefinition(
                        name=tool.name,
                        description=tool.description or "",
                        parameters=getattr(tool, "input_schema", getattr(tool, "inputSchema", {})),
                        upstream_type=self.upstream_type,
                    )
                )
            return tool_definitions

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        """Execute a tool using the persistent upstream session with automatic recovery."""
        async with self._lock:
            try:
                session = await self._ensure_connected()
                result = await session.call_tool(name, arguments)
            except Exception as exc:
                logger.warning(
                    f"Tool call '{name}' failed on upstream '{self.upstream_type}', retrying with fresh connection: {exc}"
                )
                await self._close_session()
                session = await self._ensure_connected()
                result = await session.call_tool(name, arguments)

            # Format content
            contents = []
            for item in result.content:
                if hasattr(item, "text"):
                    contents.append(item.text)
                else:
                    contents.append(str(item))

            is_error = getattr(result, "is_error", getattr(result, "isError", False))
            return ToolResult(
                status="error" if is_error else "success",
                content="\n".join(contents)
                if len(contents) > 1
                else (contents[0] if contents else None),
                is_error=bool(is_error),
            )
