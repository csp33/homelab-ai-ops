"""Tracer interface definition for LYOKO."""

from abc import ABC, abstractmethod
from typing import Any


class TracerInterface(ABC):
    @abstractmethod
    def get_callback_handler(self) -> Any | None:
        """Return callback handler for LangGraph / LangChain tracing."""

    def get_trace_config(
        self,
        *,
        session_id: str | None = None,
        user_id: str | None = None,
        trace_name: str | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build a LangChain / LangGraph RunnableConfig dict with tracing, session, and metadata."""
        config: dict[str, Any] = {}
        handler = self.get_callback_handler()
        if handler:
            config["callbacks"] = [handler]
        if tags:
            config["tags"] = list(tags)
        if metadata:
            config["metadata"] = dict(metadata)
        if trace_name:
            config["run_name"] = trace_name
        return config
