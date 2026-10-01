"""Domain interfaces re-exports for LYOKO."""

from lyoko.domain.interfaces.llm import LLMClientInterface
from lyoko.domain.interfaces.mcp import MCPClientInterface

__all__ = [
    "LLMClientInterface",
    "MCPClientInterface",
]
