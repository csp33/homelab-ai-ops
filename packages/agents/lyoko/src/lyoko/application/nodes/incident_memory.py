"""Semantic memory query helpers for incident diagnosis."""

import logging
from typing import Any

from lyoko.domain.interfaces.embeddings import EmbeddingsServiceInterface
from lyoko.domain.interfaces.memory import MemoryRepositoryInterface

logger = logging.getLogger("lyoko.workflow.incident.memory")


async def retrieve_incident_lessons(
    state: dict[str, Any],
    memory_repository: MemoryRepositoryInterface | None,
    embeddings_service: EmbeddingsServiceInterface | None,
) -> tuple[list[dict[str, Any]], str]:
    """Retrieve relevant operator feedback and past experiences from semantic memory."""
    from lyoko.application.use_cases.retrieve_memory import RetrieveMemoryLessonsUseCase

    use_case = RetrieveMemoryLessonsUseCase(
        memory_repository=memory_repository,
        embeddings_service=embeddings_service,
    )
    return await use_case.execute_for_incident(state)
