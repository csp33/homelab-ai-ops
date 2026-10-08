import logging
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
    status_callback,
)
from lyoko.application.tool_gate import GateMode
from lyoko.application.use_cases.retrieve_memory import RetrieveMemoryLessonsUseCase
from lyoko.config import settings
from lyoko.domain.interfaces.embeddings import EmbeddingsServiceInterface
from lyoko.domain.interfaces.llm import LLMClientInterface
from lyoko.domain.interfaces.mcp import MCPClientInterface
from lyoko.domain.interfaces.memory import MemoryRepositoryInterface
from lyoko.domain.interfaces.supervisor import SupervisorInterface

logger = logging.getLogger("lyoko.application.use_cases.diagnose_incident")


class DiagnoseIncidentUseCase:
    """Investigates an incident in read-only mode and formulates a root cause and plan."""

    def __init__(
        self,
        mcp_client: MCPClientInterface | None,
        llm: LLMClientInterface | None,
        supervisor: SupervisorInterface | None = None,
        approval_manager: ApprovalManager | None = None,
        chat_manager: ChatManager | None = None,
        retrieve_memory_use_case: RetrieveMemoryLessonsUseCase | None = None,
        memory_repository: MemoryRepositoryInterface | None = None,
        embeddings_service: EmbeddingsServiceInterface | None = None,
        runner: Any = None,
    ) -> None:
        self.mcp_client = mcp_client
        self.llm = llm
        self.supervisor = supervisor
        self.approval_manager = approval_manager
        self.chat_manager = chat_manager
        self.runner = runner or run_supervised
        self.retrieve_memory_use_case = retrieve_memory_use_case or RetrieveMemoryLessonsUseCase(
            memory_repository=memory_repository,
            embeddings_service=embeddings_service,
        )

    async def execute(self, state: dict[str, Any], config: RunnableConfig) -> dict[str, Any]:
        """Investigate read-only and decide whether a fix is possible."""
        if self.llm is None:
            return {
                "root_cause": "Not investigated: no LLM provider is configured.",
                "requires_escalation": True,
            }

        (
            matched_memories,
            lessons_context,
        ) = await self.retrieve_memory_use_case.execute_for_incident(
            state=state,
        )

        logger.info("Diagnosing %s...", origin(state))
        progress_msg_id: str | None = state.get("progress_message_id")
        progress_chat_id: str | None = state.get("progress_chat_id")

        if self.chat_manager is not None and not is_message(state) and not progress_msg_id:
            chat_id = state.get("chat_id") or settings.telegram_default_chat_id or ""
            if chat_id:
                status_text = format_diagnosing_status(state)
                sent_list = await self.chat_manager.broadcast_message(
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
            approval_manager=self.approval_manager,
            chat_manager=self.chat_manager,
            mcp_client=self.mcp_client,
        )
        try:
            prompt_content = f"Investigate this.\n\n{incident_context(state)}{lessons_context}"
            answer = await self.runner(
                state,
                gate,
                config,
                mcp_client=self.mcp_client,
                llm=self.llm,
                supervisor=self.supervisor,
                phase="diagnose",
                system_prompt=DIAGNOSE_SYSTEM_PROMPT,
                prompt=prompt_content,
                on_status=status_callback(config),
            )
        except Exception as exc:
            logger.error("Investigation failed: %s", exc, exc_info=True)
            return {"root_cause": f"Investigation failed: {exc}", "requires_escalation": True}

        diagnosis = parse_diagnosis(answer)
        if self.chat_manager is not None and progress_msg_id and progress_chat_id:
            status_text = format_remediating_status(
                state,
                diagnosis.root_cause,
                requires_escalation=not diagnosis.actionable,
            )
            await self.chat_manager.edit_message(
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
