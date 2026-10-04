"""Chat branch node answering operator queries with tool-gate safety and semantic memory."""

import logging
from collections.abc import Callable
from typing import Any

from langchain_core.runnables import RunnableConfig
from lyoko.application.chat_manager import ChatManager
from lyoko.application.chat_prompts import CHAT_SYSTEM_PROMPT
from lyoko.application.hitl import ApprovalManager
from lyoko.application.nodes.helpers import (
    _NO_LLM_REPLY,
    make_gate,
    run_supervised,
)
from lyoko.application.tool_gate import GateMode
from lyoko.config import settings
from lyoko.domain.interfaces.llm import LLMClientInterface

logger = logging.getLogger("lyoko.workflow.chat")


def create_chat_node(
    mcp_client: Any,
    llm: LLMClientInterface | None,
    supervisor: Any = None,
    approval_manager: ApprovalManager | None = None,
    chat_manager: ChatManager | None = None,
    memory_repository: Any = None,
    embeddings_service: Any = None,
) -> Callable[[dict[str, Any], RunnableConfig], Any]:
    """Factory creating the chat node handler with injected dependencies."""

    async def chat_node(state: dict[str, Any], config: RunnableConfig) -> dict[str, Any]:
        """Answer the operator. Coordinates through the multi-agent supervisor with ToolGate safety."""
        text = state.get("text", "")
        history_context = state.get("history_context", "")
        if llm is None:
            return {"reply": _NO_LLM_REPLY.format(text=text)}

        # Query semantic memory for relevant past experiences / operator feedback
        lessons_context = ""
        if memory_repository is not None:
            try:
                query_embedding = None
                if embeddings_service is not None:
                    query_embedding = await embeddings_service.embed_text(text)

                memories = await memory_repository.search_memories(
                    query_embedding=query_embedding,
                    limit=3,
                    min_similarity=settings.memory_similarity_threshold,
                )

                if memories:
                    lessons_lines = []
                    for m in memories:
                        lessons_lines.append(
                            f"- [Relevance: {m.similarity:.0%}] Operator Rule: '{m.memory.operator_feedback}'"
                            + (
                                f" | Context: {m.memory.incident_pattern}"
                                if m.memory.incident_pattern
                                else ""
                            )
                        )
                    lessons_context = (
                        "\n\n--- PRIOR OPERATOR PREFERENCES & LEARNED RULES ---\n"
                        + "\n".join(lessons_lines)
                        + "\n----------------------------------------------------\n"
                    )
                    logger.info(
                        f"Retrieved {len(memories)} relevant past memories/preferences for chat query: {text[:50]}"
                    )
            except Exception as exc:
                logger.warning("Failed to query semantic memory in chat: %s", exc, exc_info=True)

        prompt_with_memory = f"{text}{lessons_context}{history_context}"
        gate = make_gate(
            state,
            GateMode.APPROVAL,
            approval_manager=approval_manager,
            chat_manager=chat_manager,
        )
        on_token = None
        if isinstance(config, dict):
            on_token = config.get("configurable", {}).get("on_token")
        try:
            answer = await run_supervised(
                state,
                gate,
                config,
                mcp_client=mcp_client,
                llm=llm,
                supervisor=supervisor,
                phase="chat",
                prompt=prompt_with_memory,
                system_prompt=None if supervisor is not None else CHAT_SYSTEM_PROMPT,
                on_token=on_token,
            )
        except Exception as exc:
            logger.error("Failed to generate LLM response: %s", exc)
            return {"reply": f"⚠️ Error processing your question: {exc}"}
        return {"reply": answer, "actions": [r.to_dict() for r in gate.records]}

    return chat_node
