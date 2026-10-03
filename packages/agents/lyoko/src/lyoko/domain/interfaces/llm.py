"""LLM client interface definitions for LYOKO."""

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from typing import Any

TokenCallback = Callable[[str], Awaitable[None]]


class LLMClientInterface(ABC):
    """Domain interface for Large Language Model interactions."""

    @abstractmethod
    async def chat(
        self,
        prompt: str,
        system_prompt: str | None = None,
        tools: list[Any] | None = None,
        session_id: str | None = None,
        user_id: str | None = None,
        trace_name: str | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        max_steps: int | None = None,
        parent_config: dict[str, Any] | None = None,
        on_token: TokenCallback | None = None,
    ) -> str:
        """Process a conversational or single-turn prompt with optional tools and session tracing.

        ``max_steps`` bounds the number of tool-use iterations when ``tools`` are given.

        ``parent_config`` is the run configuration of the graph node making the call. When it is
        given, the call is traced as a child of that run (named ``trace_name``) instead of
        starting a trace of its own, and ``session_id`` and ``user_id`` are ignored because the
        enclosing trace already carries them.

        ``on_token`` is an optional async callback invoked as text tokens are streamed.
        """
