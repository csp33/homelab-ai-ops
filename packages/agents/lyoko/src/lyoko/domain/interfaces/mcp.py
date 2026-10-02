"""MCP client interface definitions for LYOKO."""

from abc import ABC, abstractmethod
from typing import Any


class MCPClientInterface(ABC):
    @abstractmethod
    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        """Execute a tool on the MCP gateway."""

    @abstractmethod
    def get_langchain_tools(self) -> list[Any]:
        """Return list of LangChain tools."""

    @abstractmethod
    async def verify_connection(self) -> None:
        """Check that the gateway is reachable and accepts our credentials.

        Raises:
            MCPAuthenticationError: credentials were rejected.
            MCPEndpointNotFoundError: the configured URL is not an MCP endpoint.
            MCPGatewayUnreachableError: the gateway could not be reached.
            MCPGatewayError: any other unexpected gateway failure.
        """
