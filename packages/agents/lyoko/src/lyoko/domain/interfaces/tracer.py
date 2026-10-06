"""Tracer interface definition for LYOKO."""

from abc import ABC, abstractmethod
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any


@contextmanager
def null_span() -> Iterator[None]:
    yield None


class TracerInterface(ABC):
    @abstractmethod
    def get_callback_handler(self) -> Any | None:
        """Return callback handler for LangGraph / LangChain tracing."""

    def span(self, name: str, metadata: dict[str, Any] | None = None) -> Any:
        """Record a named span in the current trace. A no-op unless tracing is enabled.

        Used by code paths that call infrastructure directly (no LLM/LangChain run to trace), so
        their steps still show up in the trace under the enclosing graph node.
        """
        return null_span()

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
