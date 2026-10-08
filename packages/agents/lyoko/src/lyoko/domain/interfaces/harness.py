"""Domain port interface for agent execution harnesses."""

from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any


class AgentHarnessInterface(ABC):
    """Abstract port for running bounded reasoning and tool execution loops."""

    @abstractmethod
    async def execute(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
        tools: list[Any] | None = None,
        session_id: str | None = None,
        trace_name: str | None = None,
        tags: list[str] | None = None,
        max_steps: int | None = None,
        parent_config: dict[str, Any] | None = None,
        on_status: Callable[[str], Any] | None = None,
    ) -> str:
        """Execute the harness loop until the agent completes or a budget trips."""
