"""Coordinator node: routes between supervisor reasoning, specialists, remediation, and notification."""

import logging
from collections.abc import Callable
from typing import Any

from langchain_core.runnables import RunnableConfig
from lyoko.application.chat_manager import ChatManager
from lyoko.application.hitl import ApprovalManager
from lyoko.application.nodes.chat import create_chat_node
from lyoko.application.nodes.helpers import is_message
from lyoko.application.nodes.incident_diagnose import create_diagnose_node
from lyoko.domain.interfaces.embeddings import EmbeddingsServiceInterface
from lyoko.domain.interfaces.llm import LLMClientInterface
from lyoko.domain.interfaces.memory import MemoryRepositoryInterface

logger = logging.getLogger("lyoko.workflow.coordinator")

SPECIALIST_DOMAINS = frozenset({"kubernetes", "unifi", "homeassistant", "grafana"})


def choose_coordinator_next(state: dict[str, Any]) -> str:
    """Determine the next node after coordinator execution.

    - If a specialist delegation is pending, route to that specialist node.
    - If event is chat (message) or incident is non-actionable/resolved, route to notify.
    - If incident is actionable and needs fixing, route to remediate.
    """
    pending = state.get("pending_delegation")
    if pending and isinstance(pending, dict):
        domain = pending.get("domain")
        if domain in SPECIALIST_DOMAINS:
            return domain

    # Chat branch resolution goes directly to END (reply is already formatted)
    if is_message(state) and state.get("route") != "incident":
        return "chat_end"

    # For alerts / incidents: coordinator diagnosis leads to remediate.
    # remediate and verify handle non-actionable or escalated incidents safely.
    return "remediate"


def create_coordinator_node(
    mcp_client: Any,
    llm: LLMClientInterface | None,
    supervisor: Any = None,
    approval_manager: ApprovalManager | None = None,
    chat_manager: ChatManager | None = None,
    memory_repository: MemoryRepositoryInterface | None = None,
    embeddings_service: EmbeddingsServiceInterface | None = None,
    diagnose_llm: LLMClientInterface | None = None,
    diagnose_supervisor: Any = None,
) -> Callable[[dict[str, Any], RunnableConfig], Any]:
    """Factory creating the unified coordinator node handler."""
    chat_handler = create_chat_node(
        mcp_client=mcp_client,
        llm=llm,
        supervisor=supervisor,
        approval_manager=approval_manager,
        chat_manager=chat_manager,
        memory_repository=memory_repository,
        embeddings_service=embeddings_service,
    )
    diagnose_handler = create_diagnose_node(
        mcp_client=mcp_client,
        llm=diagnose_llm or llm,
        supervisor=diagnose_supervisor or supervisor,
        approval_manager=approval_manager,
        chat_manager=chat_manager,
        memory_repository=memory_repository,
        embeddings_service=embeddings_service,
    )

    async def coordinator_node(state: dict[str, Any], config: RunnableConfig) -> dict[str, Any]:
        """Execute coordinator turn for either chat or incident investigation."""
        logger.info(
            "Executing coordinator node for event_type='%s', route='%s'",
            state.get("event_type"),
            state.get("route"),
        )
        if is_message(state) and state.get("route") != "incident":
            return await chat_handler(state, config)
        return await diagnose_handler(state, config)

    return coordinator_node
