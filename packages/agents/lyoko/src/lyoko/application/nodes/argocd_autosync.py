"""Fast-path triage node for a known Argo CD OutOfSync + autosync-disabled alert.

Instead of spending a multi-agent LLM investigation on a one-field, reversible change, this node
reads the Application, and when autosync is disabled it enables it directly through the same
``ToolGate`` policy (so the change still needs operator approval) and verifies the result
deterministically. Anything it does not recognize falls through to the normal ``diagnose`` node.
"""

import logging
from collections.abc import Callable
from typing import Any

from langchain_core.runnables import RunnableConfig
from lyoko.application.chat_manager import ChatManager
from lyoko.application.hitl import ApprovalManager
from lyoko.application.use_cases.triage_argocd_autosync import (
    TRIAGE_DIAGNOSE,
    TRIAGE_HANDLED,
    TriageArgoCDAutosyncUseCase,
)
from lyoko.domain.interfaces.mcp import MCPClientInterface

logger = logging.getLogger("lyoko.workflow.autosync")

# Argo CD reconciles asynchronously after the manifest change, so poll for a bounded time.
_VERIFY_ATTEMPTS = 6

_GET_TOOL = "k8s_resources_get"
_APPLY_TOOL = "k8s_resources_create_or_update"
_APPLICATION = {
    "apiVersion": "argoproj.io/v1alpha1",
    "kind": "Application",
    "namespace": "argocd",
}


def choose_triage(state: dict[str, Any]) -> str:
    """Route a handled fast-path incident to notify, otherwise continue to diagnose."""
    return TRIAGE_HANDLED if state.get("triage") == TRIAGE_HANDLED else TRIAGE_DIAGNOSE


def _status_line(manifest: dict[str, Any]) -> str:
    status = manifest.get("status") or {}
    sync = (status.get("sync") or {}).get("status", "Unknown")
    health = (status.get("health") or {}).get("status", "Unknown")
    return f"sync={sync} health={health}"


def create_argocd_autosync_node(
    mcp_client: MCPClientInterface | None,
    approval_manager: ApprovalManager | None = None,
    chat_manager: ChatManager | None = None,
    tracer: Any = None,
) -> Callable[[dict[str, Any], RunnableConfig], Any]:
    """Factory creating the deterministic Argo CD autosync triage node."""
    use_case = TriageArgoCDAutosyncUseCase(
        mcp_client=mcp_client,
        approval_manager=approval_manager,
        chat_manager=chat_manager,
        tracer=tracer,
    )

    async def argocd_autosync_node(state: dict[str, Any], config: RunnableConfig) -> dict[str, Any]:
        return await use_case.execute(state, config)

    return argocd_autosync_node
