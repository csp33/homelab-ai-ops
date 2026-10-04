"""Embeddings service interface definitions for LYOKO."""

from abc import ABC, abstractmethod


class EmbeddingsServiceInterface(ABC):
    """Domain port for computing dense vector embeddings."""

    @abstractmethod
    async def embed_text(self, text: str) -> list[float] | None:
        """Return a dense vector embedding for ``text``, or None when unavailable."""
