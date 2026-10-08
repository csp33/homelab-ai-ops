"""Abstract interface for multi-agent supervisor orchestrators."""

from abc import ABC, abstractmethod
from typing import Any


class SupervisorInterface(ABC):
    """Orchestrates domain specialist subagents and plans multi-step cross-domain tasks."""

    @abstractmethod
    def get_specialist(self, domain: str) -> Any | None:
        """Retrieve a specialist by domain name."""

    @abstractmethod
    async def delegate(
        self,
        domain: str,
        prompt: str,
        session_id: str | None = None,
        user_id: str | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        authorizer: Any = None,
        parent_config: Any = None,
        on_status: Any = None,
    ) -> str:
        """Delegate a task directly to a specific domain specialist."""

    @abstractmethod
    def get_delegation_tools(
        self,
        *,
        authorizer: Any = None,
        session_id: str | None = None,
        user_id: str | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        parent_config: Any = None,
        on_status: Any = None,
    ) -> list[Any]:
        """Return tools per registered specialist for supervisor delegation."""

    @abstractmethod
    async def coordinate(
        self,
        prompt: str,
        session_id: str | None = None,
        user_id: str | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        tools: list[Any] | None = None,
        system_prompt: str | None = None,
        authorizer: Any = None,
        parent_config: Any = None,
        max_steps: int | None = None,
        on_status: Any = None,
    ) -> str:
        """Coordinate multi-agent task execution by delegating to domain specialists."""
