"""Tracer interface definition for LYOKO."""

from abc import ABC, abstractmethod
from typing import Any


class TracerInterface(ABC):
    @abstractmethod
    def get_callback_handler(self) -> Any | None:
        """Return callback handler for LangGraph / LangChain tracing."""
