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
