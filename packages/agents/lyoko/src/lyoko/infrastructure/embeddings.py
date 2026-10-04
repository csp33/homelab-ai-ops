"""Embeddings service for semantic search and memory indexing."""

import logging

from langchain_openai import OpenAIEmbeddings
from lyoko.config import settings
from lyoko.domain.interfaces.embeddings import EmbeddingsServiceInterface

logger = logging.getLogger("lyoko.embeddings")


class EmbeddingsService(EmbeddingsServiceInterface):
    """Service to compute dense vector embeddings for incident patterns and operator feedback."""

    def __init__(self, api_key: str | None = None, model: str = "text-embedding-3-small") -> None:
        self.api_key = api_key or settings.openai_api_key
        self.model_name = model
        self._embeddings = None

        if self.api_key and not self.api_key.startswith("sk-dummy"):
            try:
                self._embeddings = OpenAIEmbeddings(
                    model=self.model_name,
                    api_key=self.api_key,
                )
            except Exception as exc:
                logger.warning(f"Failed to initialize OpenAIEmbeddings: {exc}")
                self._embeddings = None

    async def embed_text(self, text: str) -> list[float] | None:
        """Generate a dense vector embedding for the given text."""
        if not text or not text.strip():
            return None

        if self._embeddings is None:
            return None

        try:
            # LangChain OpenAIEmbeddings uses aembed_query
            embedding = await self._embeddings.aembed_query(text)
            return embedding
        except Exception as exc:
            logger.warning(f"Error computing embedding for text '{text[:50]}...': {exc}")
            return None
