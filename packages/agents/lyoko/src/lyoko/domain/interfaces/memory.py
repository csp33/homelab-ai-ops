"""Memory repository interface definitions for LYOKO."""

from abc import ABC, abstractmethod

from lyoko.domain.models.memory import MemoryEntry, MemoryQueryResult


class MemoryRepositoryInterface(ABC):
    """Domain port for persistent semantic memory and operator feedback."""

    @abstractmethod
    async def save_memory(
        self,
        entry: MemoryEntry,
        embedding: list[float] | None = None,
    ) -> int:
        """Persist a memory entry with an optional vector embedding and return its id."""

    @abstractmethod
    async def search_memories(
        self,
        query_embedding: list[float] | None = None,
        namespace: str | None = None,
        service_name: str | None = None,
        limit: int = 3,
        min_similarity: float = 0.0,
    ) -> list[MemoryQueryResult]:
        """Search memories by vector similarity or metadata filtering."""

    @abstractmethod
    async def list_recent_memories(self, limit: int = 50) -> list[MemoryEntry]:
        """List recent memories for inspection."""
