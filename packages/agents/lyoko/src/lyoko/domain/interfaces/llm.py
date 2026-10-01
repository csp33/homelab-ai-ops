"""LLM client interface definitions for LYOKO."""

from abc import ABC, abstractmethod
from typing import Any


class LLMClientInterface(ABC):
    @abstractmethod
    async def generate_remediation_plan(self, context: dict[str, Any]) -> str:
        """Generate automated remediation steps from diagnostic incident context."""
