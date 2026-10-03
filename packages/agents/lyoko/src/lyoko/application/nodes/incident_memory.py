"""Semantic memory query helpers for incident diagnosis."""

import logging
from typing import Any

logger = logging.getLogger("lyoko.workflow.incident.memory")


async def retrieve_incident_lessons(
    state: dict[str, Any],
    memory_repository: Any,
    embeddings_service: Any,
) -> tuple[list[dict[str, Any]], str]:
    """Retrieve relevant operator feedback and past experiences from semantic memory."""
    if memory_repository is None:
        return [], ""

    matched_memories: list[dict[str, Any]] = []
    lessons_context = ""

    try:
        alert_name = state.get("alert_name", "UnknownAlert")
        labels = state.get("labels") or {}
        namespace = labels.get("namespace")
        service_name = labels.get("deployment") or labels.get("app") or labels.get("container")
        incident_query = f"{alert_name} {namespace} {service_name} {state.get('text', '')}"
        query_embedding = None
        if embeddings_service is not None:
            query_embedding = await embeddings_service.embed_text(incident_query)

        memories = await memory_repository.search_memories(
            query_embedding=query_embedding,
            namespace=namespace,
            service_name=service_name,
            limit=3,
        )

        if memories:
            lessons_lines = []
            for m in memories:
                matched_memories.append(m.memory.model_dump())
                lessons_lines.append(
                    f"- [Relevance: {m.similarity:.0%}] Pattern: {m.memory.incident_pattern} | "
                    f"Operator Rule: '{m.memory.operator_feedback}'"
                    + (
                        f" | Recommended Action: {m.memory.action_rule}"
                        if m.memory.action_rule
                        else ""
                    )
                )
            lessons_context = (
                "\n\n--- PRIOR OPERATOR FEEDBACK & LESSONS LEARNED ---\n"
                + "\n".join(lessons_lines)
                + "\n------------------------------------------------\n"
            )
            logger.info(
                "Retrieved %s relevant past lessons for %s",
                len(memories),
                service_name or namespace,
            )
    except Exception as exc:
        logger.warning("Failed to query semantic memory: %s", exc, exc_info=True)

    return matched_memories, lessons_context
