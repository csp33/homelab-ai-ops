"""Diagnose node: read-only investigation that returns a root cause, a plan, and fixability."""

import logging
from collections.abc import Callable
from typing import Any

from langchain_core.runnables import RunnableConfig
from lyoko.application.skills.matcher import SkillMatcherService
from lyoko.application.supervisor import run_supervised
from lyoko.application.use_cases.diagnose_incident import DiagnoseIncidentUseCase
from lyoko.domain.interfaces.approval import ApprovalManagerInterface
from lyoko.domain.interfaces.chat_service import ChatServiceInterface
from lyoko.domain.interfaces.embeddings import EmbeddingsServiceInterface
from lyoko.domain.interfaces.llm import LLMClientInterface
from lyoko.domain.interfaces.mcp import MCPClientInterface
from lyoko.domain.interfaces.memory import MemoryRepositoryInterface
from lyoko.domain.interfaces.supervisor import SupervisorInterface

logger = logging.getLogger("lyoko.workflow.incident")


def create_diagnose_node(
    mcp_client: MCPClientInterface | None,
    llm: LLMClientInterface | None,
    supervisor: SupervisorInterface | None = None,
    approval_manager: ApprovalManagerInterface | None = None,
    chat_manager: ChatServiceInterface | None = None,
    memory_repository: MemoryRepositoryInterface | None = None,
    embeddings_service: EmbeddingsServiceInterface | None = None,
    skill_matcher_service: SkillMatcherService | None = None,
) -> Callable[[dict[str, Any], RunnableConfig], Any]:
    """Factory creating the diagnose node handler."""

    async def diagnose_node(state: dict[str, Any], config: RunnableConfig) -> dict[str, Any]:
        """Investigate read-only and decide whether a fix is possible."""
        use_case = DiagnoseIncidentUseCase(
            mcp_client=mcp_client,
            llm=llm,
            supervisor=supervisor,
            approval_manager=approval_manager,
            chat_manager=chat_manager,
            memory_repository=memory_repository,
            embeddings_service=embeddings_service,
            skill_matcher_service=skill_matcher_service,
            runner=run_supervised,
        )
        return await use_case.execute(state, config=config)

    return diagnose_node
