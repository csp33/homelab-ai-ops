"""Triage node for fast-path deterministic resolution of known alerts.

Evaluates registered deterministic triage handlers (Argo CD autosync, pod crashloops,
Cloudflare tunnel restarts, Argo CD sync failures) before delegating to multi-agent diagnosis.
"""

from collections.abc import Callable
from typing import Any

from langchain_core.runnables import RunnableConfig
from lyoko.application.chat_manager import ChatManager
from lyoko.application.hitl import ApprovalManager
from lyoko.application.triage.argocd_autosync import ArgoCDAutosyncHandler
from lyoko.application.triage.argocd_sync_failed import ArgoCDSyncFailedHandler
from lyoko.application.triage.cloudflare_tunnel import CloudflareTunnelHandler
from lyoko.application.triage.dispatcher import (
    TRIAGE_DIAGNOSE,
    TRIAGE_HANDLED,
    choose_triage,
    create_triage_node,
)
from lyoko.application.triage.pod_crashloop import PodCrashLoopHandler
from lyoko.domain.interfaces.mcp import MCPClientInterface

__all__ = [
    "TRIAGE_DIAGNOSE",
    "TRIAGE_HANDLED",
    "choose_triage",
    "create_argocd_autosync_node",
    "create_composite_triage_node",
]


def create_composite_triage_node(
    mcp_client: MCPClientInterface | None,
    approval_manager: ApprovalManager | None = None,
    chat_manager: ChatManager | None = None,
    tracer: Any = None,
) -> Callable[[dict[str, Any], RunnableConfig], Any]:
    """Factory creating the composite deterministic triage node with all registered handlers."""
    handlers = [
        ArgoCDAutosyncHandler(
            mcp_client=mcp_client,
            approval_manager=approval_manager,
            chat_manager=chat_manager,
            tracer=tracer,
        ),
        PodCrashLoopHandler(
            mcp_client=mcp_client,
            approval_manager=approval_manager,
            chat_manager=chat_manager,
            tracer=tracer,
        ),
        CloudflareTunnelHandler(
            mcp_client=mcp_client,
            approval_manager=approval_manager,
            chat_manager=chat_manager,
            tracer=tracer,
        ),
        ArgoCDSyncFailedHandler(
            mcp_client=mcp_client,
            approval_manager=approval_manager,
            chat_manager=chat_manager,
            tracer=tracer,
        ),
    ]
    return create_triage_node(handlers)


def create_argocd_autosync_node(
    mcp_client: MCPClientInterface | None,
    approval_manager: ApprovalManager | None = None,
    chat_manager: ChatManager | None = None,
    tracer: Any = None,
) -> Callable[[dict[str, Any], RunnableConfig], Any]:
    """Backward-compatibility alias creating a single-handler autosync triage node."""
    handler = ArgoCDAutosyncHandler(
        mcp_client=mcp_client,
        approval_manager=approval_manager,
        chat_manager=chat_manager,
        tracer=tracer,
    )
    return create_triage_node([handler])
