"""Domain port interface for persisting and reading scratchpad tool outputs."""

from abc import ABC, abstractmethod

from lyoko.domain.models.scratchpad import ScratchpadReference


class ScratchpadStorageInterface(ABC):
    """Abstract port for saving raw tool output payloads and retrieving them."""

    @abstractmethod
    async def store_output(
        self,
        tool_name: str,
        raw_output: str,
        session_id: str | None = None,
    ) -> ScratchpadReference:
        """Persist a raw output to scratchpad storage and return a reference pointer."""

    @abstractmethod
    async def read_output(self, reference_id: str) -> str | None:
        """Retrieve raw output by its reference identifier."""
