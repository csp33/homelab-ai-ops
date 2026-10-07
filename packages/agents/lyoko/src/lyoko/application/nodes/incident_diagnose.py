"""Diagnose node: read-only investigation that returns a root cause, a plan, and fixability."""

import logging
from collections.abc import Callable
from typing import Any

from langchain_core.runnables import RunnableConfig
from lyoko.application.chat_manager import ChatManager
from lyoko.application.hitl import ApprovalManager
from lyoko.application.nodes.helpers import run_supervised
from lyoko.domain.interfaces.embeddings import EmbeddingsServiceInterface
from lyoko.domain.interfaces.llm import LLMClientInterface
from lyoko.domain.interfaces.memory import MemoryRepositoryInterface

logger = logging.getLogger("lyoko.workflow.incident")

__all__ = ["create_diagnose_node", "run_supervised"]


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
    from lyoko.application.use_cases.diagnose_incident import DiagnoseIncidentUseCase

    use_case = DiagnoseIncidentUseCase(
        mcp_client=mcp_client,
        llm=llm,
        supervisor=supervisor,
        approval_manager=approval_manager,
        chat_manager=chat_manager,
        memory_repository=memory_repository,
        embeddings_service=embeddings_service,
    )

    async def diagnose_node(state: dict[str, Any], config: RunnableConfig) -> dict[str, Any]:
        """Investigate read-only and decide whether a fix is possible."""
        return await use_case.execute(state, config=config)

    return diagnose_node
