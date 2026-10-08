"""Coordinator node: routes between supervisor reasoning, specialists, remediation, and notification."""

import logging
from collections.abc import Callable
from typing import Any

from langchain_core.runnables import RunnableConfig
from lyoko.application.use_cases.coordinate_workflow import CoordinateWorkflowUseCase
from lyoko.domain.interfaces.approval import ApprovalManagerInterface
from lyoko.domain.interfaces.chat_service import ChatServiceInterface
from lyoko.domain.interfaces.embeddings import EmbeddingsServiceInterface
from lyoko.domain.interfaces.llm import LLMClientInterface
from lyoko.domain.interfaces.mcp import MCPClientInterface
from lyoko.domain.interfaces.memory import MemoryRepositoryInterface
from lyoko.domain.interfaces.supervisor import SupervisorInterface
from lyoko.domain.models.incident import CoordinatorNext, SpecialistDomain
from lyoko.domain.models.state import is_message

logger = logging.getLogger("lyoko.workflow.coordinator")

SPECIALIST_DOMAINS = frozenset(SpecialistDomain)


def choose_coordinator_next(state: dict[str, Any]) -> CoordinatorNext:
    """Determine the next node after coordinator execution.

    - If a specialist delegation is pending, route to that specialist node.
    - If event is chat (message), route to END.
    - If incident, route to remediate.
    """
    pending = state.get("pending_delegation")
    if pending and isinstance(pending, dict):
        domain = pending.get("domain")
        if domain in SPECIALIST_DOMAINS:
            return CoordinatorNext(domain)

    # Chat branch resolution goes directly to END (reply is already formatted)
    if is_message(state) and state.get("route") != "incident":
        return CoordinatorNext.CHAT_END

    # For alerts / incidents: coordinator diagnosis leads to remediate.
    # remediate and verify handle non-actionable or escalated incidents safely.
    return CoordinatorNext.REMEDIATE


def create_coordinator_node(
    mcp_client: MCPClientInterface | None,
    llm: LLMClientInterface | None,
    supervisor: SupervisorInterface | None = None,
    approval_manager: ApprovalManagerInterface | None = None,
    chat_manager: ChatServiceInterface | None = None,
    memory_repository: MemoryRepositoryInterface | None = None,
    embeddings_service: EmbeddingsServiceInterface | None = None,
    diagnose_llm: LLMClientInterface | None = None,
    diagnose_supervisor: SupervisorInterface | None = None,
    skill_matcher_service: Any = None,
) -> Callable[[dict[str, Any], RunnableConfig], Any]:
    """Factory creating the unified coordinator node handler."""
    use_case = CoordinateWorkflowUseCase(
        mcp_client=mcp_client,
        llm=llm,
        supervisor=supervisor,
        approval_manager=approval_manager,
        chat_manager=chat_manager,
        memory_repository=memory_repository,
        embeddings_service=embeddings_service,
        diagnose_llm=diagnose_llm,
        diagnose_supervisor=diagnose_supervisor,
        skill_matcher_service=skill_matcher_service,
    )

    async def coordinator_node(state: dict[str, Any], config: RunnableConfig) -> dict[str, Any]:
        """Thin adapter delegating execution to CoordinateWorkflowUseCase."""
        return await use_case.execute(state, config=config)

    return coordinator_node
