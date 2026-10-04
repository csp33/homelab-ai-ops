"""Diagnose node: read-only investigation that returns a root cause, a plan, and fixability."""

import logging
from collections.abc import Callable
from typing import Any

from langchain_core.runnables import RunnableConfig
from lyoko.application.chat_manager import ChatManager
from lyoko.application.hitl import ApprovalManager
from lyoko.application.incident_prompts import DIAGNOSE_SYSTEM_PROMPT, parse_diagnosis
from lyoko.application.incident_status import (
    format_diagnosing_status,
    format_remediating_status,
)
from lyoko.application.nodes.helpers import (
    incident_context,
    is_message,
    make_gate,
    origin,
    run_supervised,
)
from lyoko.application.nodes.incident_memory import retrieve_incident_lessons
from lyoko.application.tool_gate import GateMode
from lyoko.config import settings
from lyoko.domain.interfaces.embeddings import EmbeddingsServiceInterface
from lyoko.domain.interfaces.llm import LLMClientInterface
from lyoko.domain.interfaces.memory import MemoryRepositoryInterface

logger = logging.getLogger("lyoko.workflow.incident")


def create_diagnose_node(
    mcp_client: Any,
    llm: LLMClientInterface | None,
    supervisor: Any = None,
    approval_manager: ApprovalManager | None = None,
    chat_manager: ChatManager | None = None,
    memory_repository: MemoryRepositoryInterface | None = None,
    embeddings_service: EmbeddingsServiceInterface | None = None,
) -> Callable[[dict[str, Any], RunnableConfig], Any]:
    """Factory creating the diagnose node handler."""

    async def diagnose_node(state: dict[str, Any], config: RunnableConfig) -> dict[str, Any]:
        """Investigate read-only and decide whether a fix is possible."""
        if llm is None:
            return {
                "root_cause": "Not investigated: no LLM provider is configured.",
                "requires_escalation": True,
            }

        matched_memories, lessons_context = await retrieve_incident_lessons(
            state=state,
            memory_repository=memory_repository,
            embeddings_service=embeddings_service,
        )

        logger.info("Diagnosing %s...", origin(state))
        progress_msg_id: str | None = state.get("progress_message_id")
        progress_chat_id: str | None = state.get("progress_chat_id")

        if chat_manager is not None and not is_message(state) and not progress_msg_id:
            chat_id = state.get("chat_id") or settings.telegram_default_chat_id or ""
            if chat_id:
                status_text = format_diagnosing_status(state)
                sent_list = await chat_manager.broadcast_message(
                    chat_id=chat_id,
                    text=status_text,
                    session_id=state.get("session_id"),
                )
                if sent_list:
                    progress_msg_id = sent_list[0].message_id
                    progress_chat_id = sent_list[0].chat_id

        gate = make_gate(
            state,
            GateMode.READ_ONLY,
            approval_manager=approval_manager,
            chat_manager=chat_manager,
        )
        try:
            prompt_content = f"Investigate this.\n\n{incident_context(state)}{lessons_context}"
            answer = await run_supervised(
                state,
                gate,
                config,
                mcp_client=mcp_client,
                llm=llm,
                supervisor=supervisor,
                phase="diagnose",
                system_prompt=DIAGNOSE_SYSTEM_PROMPT,
                prompt=prompt_content,
            )
        except Exception as exc:
            logger.error("Investigation failed: %s", exc, exc_info=True)
            return {"root_cause": f"Investigation failed: {exc}", "requires_escalation": True}

        diagnosis = parse_diagnosis(answer)
        if chat_manager is not None and progress_msg_id and progress_chat_id:
            status_text = format_remediating_status(
                state,
                diagnosis.root_cause,
                requires_escalation=not diagnosis.actionable,
            )
            await chat_manager.edit_message(
                chat_id=progress_chat_id,
                message_id=progress_msg_id,
                text=status_text,
            )

        return {
            "root_cause": diagnosis.root_cause,
            "plan": diagnosis.plan,
            "requires_escalation": not diagnosis.actionable,
            "matched_memories": matched_memories,
            "lessons_context": lessons_context,
            "progress_message_id": progress_msg_id,
            "progress_chat_id": progress_chat_id,
        }

    return diagnose_node
