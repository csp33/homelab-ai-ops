"""MCP client interface definitions for LYOKO."""

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from typing import Any

ToolAuthorizer = Callable[[str, dict[str, Any]], Awaitable[str | None]]
"""Decides whether an agent may call a gateway tool.

Receives the tool name and its arguments. Returns ``None`` to allow the call, or a
human-readable refusal that is shown to the agent instead of running the tool.
"""


class MCPClientInterface(ABC):
    @abstractmethod
    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        """Execute a tool on the MCP gateway."""

    @abstractmethod
    def get_langchain_tools(self, authorizer: ToolAuthorizer | None = None) -> list[Any]:
        """Return the LangChain tools an agent uses to discover and call gateway tools.

        When an ``authorizer`` is given, every ``gateway_call_tool`` invocation is checked by
        it first, and a refusal is surfaced to the agent as a tool error.
        """

    @abstractmethod
    async def verify_connection(self) -> None:
        """Check that the gateway is reachable and accepts our credentials.

        Raises:
            MCPAuthenticationError: credentials were rejected.
            MCPEndpointNotFoundError: the configured URL is not an MCP endpoint.
            MCPGatewayUnreachableError: the gateway could not be reached.
            MCPGatewayError: any other unexpected gateway failure.
        """
