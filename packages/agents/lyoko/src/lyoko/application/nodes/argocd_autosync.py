"""Fast-path triage node for a known Argo CD OutOfSync + autosync-disabled alert.

Backward-compatibility wrapper delegating to ``ArgoCDAutosyncHandler`` and ``create_triage_node``.
"""

from collections.abc import Callable
from typing import Any

from langchain_core.runnables import RunnableConfig
from lyoko.application.chat_manager import ChatManager
from lyoko.application.hitl import ApprovalManager
from lyoko.application.triage.argocd_autosync import ArgoCDAutosyncHandler
from lyoko.application.triage.dispatcher import (
    TRIAGE_DIAGNOSE,
    TRIAGE_HANDLED,
    choose_triage,
    create_triage_node,
)
from lyoko.domain.interfaces.mcp import MCPClientInterface

__all__ = [
    "TRIAGE_DIAGNOSE",
    "TRIAGE_HANDLED",
    "choose_triage",
    "create_argocd_autosync_node",
]


def create_argocd_autosync_node(
    mcp_client: MCPClientInterface | None,
    approval_manager: ApprovalManager | None = None,
    chat_manager: ChatManager | None = None,
    tracer: Any = None,
) -> Callable[[dict[str, Any], RunnableConfig], Any]:
    """Factory creating the deterministic Argo CD autosync triage node."""
    handler = ArgoCDAutosyncHandler(
        mcp_client=mcp_client,
        approval_manager=approval_manager,
        chat_manager=chat_manager,
        tracer=tracer,
    )
    return create_triage_node([handler])
