"""LLM client interface definitions for LYOKO."""

from abc import ABC, abstractmethod
from typing import Any


class LLMClientInterface(ABC):
    """Domain interface for Large Language Model interactions."""

    @abstractmethod
    async def chat(
        self,
        prompt: str,
        system_prompt: str | None = None,
        tools: list[Any] | None = None,
    ) -> str:
        """Process a conversational or single-turn prompt and return the assistant response."""

    @abstractmethod
    async def analyze_incident(
        self,
        alert_name: str,
        pod_name: str,
        namespace: str,
        diagnostics: Any,
    ) -> str:
        """Analyze pod failure diagnostics and determine the root cause."""

    @abstractmethod
    async def generate_remediation_plan(self, context: dict[str, Any]) -> str:
        """Generate automated remediation steps from diagnostic incident context."""
