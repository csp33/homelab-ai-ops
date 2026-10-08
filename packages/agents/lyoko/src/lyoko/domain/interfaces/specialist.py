"""Domain interfaces for specialist subagents."""

from abc import ABC, abstractmethod
from typing import Any


class SpecialistAgentInterface(ABC):
    """Domain port representing a specialized domain subagent."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Name of the specialist."""

    @property
    @abstractmethod
    def domain(self) -> str:
        """Operating domain of the specialist (e.g. kubernetes, unifi, etc.)."""

    @abstractmethod
    async def run(
        self,
        prompt: str,
        session_id: str | None = None,
        user_id: str | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        authorizer: Any = None,
        parent_config: Any = None,
        on_status: Any = None,
    ) -> str:
        """Execute a domain specialist query."""
