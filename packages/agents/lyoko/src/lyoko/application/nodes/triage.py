"""Triage node for fast-path deterministic resolution of known alerts.

Acts as a thin adapter delegating to TriageIncidentUseCase before multi-agent diagnosis.
"""

from collections.abc import Callable, Sequence
from typing import Any

from langchain_core.runnables import RunnableConfig
from lyoko.application.triage.argocd_autosync import ArgoCDAutosyncHandler
from lyoko.application.triage.base import TriageHandler
from lyoko.application.use_cases.triage_incident import TriageIncidentUseCase
from lyoko.domain.interfaces.approval import ApprovalManagerInterface
from lyoko.domain.interfaces.chat_service import ChatServiceInterface
from lyoko.domain.interfaces.mcp import MCPClientInterface


def create_triage_node(
    handlers: Sequence[TriageHandler] | None = None,
    use_case: TriageIncidentUseCase | None = None,
) -> Callable[[dict[str, Any], RunnableConfig], Any]:
    """Factory creating the triage node delegating to TriageIncidentUseCase."""
    uc = use_case or TriageIncidentUseCase(handlers=handlers)

    async def triage_node(state: dict[str, Any], config: RunnableConfig) -> dict[str, Any]:
        return await uc.execute(state, config=config)

    return triage_node


def create_composite_triage_node(
    handlers: Sequence[TriageHandler],
) -> Callable[[dict[str, Any], RunnableConfig], Any]:
    """Factory creating the composite deterministic triage node with injected handlers."""
    return create_triage_node(handlers=handlers)


def create_argocd_autosync_node(
    mcp_client: MCPClientInterface | None,
    approval_manager: ApprovalManagerInterface | None = None,
    chat_manager: ChatServiceInterface | None = None,
    tracer: Any = None,
) -> Callable[[dict[str, Any], RunnableConfig], Any]:
    """Backward-compatibility alias creating a single-handler autosync triage node."""
    handler = ArgoCDAutosyncHandler(
        mcp_client=mcp_client,
        approval_manager=approval_manager,
        chat_manager=chat_manager,
        tracer=tracer,
    )
    return create_triage_node(handlers=[handler])
