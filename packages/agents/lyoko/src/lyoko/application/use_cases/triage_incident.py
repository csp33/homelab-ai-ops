"""Use case for fast-path deterministic incident triage."""

import logging
from collections.abc import Sequence
from typing import Any

from langchain_core.runnables import RunnableConfig
from lyoko.application.chat_manager import ChatManager
from lyoko.application.hitl import ApprovalManager
from lyoko.application.triage.argocd_autosync import ArgoCDAutosyncHandler
from lyoko.application.triage.argocd_sync_failed import ArgoCDSyncFailedHandler
from lyoko.application.triage.base import TriageHandler
from lyoko.application.triage.cloudflare_tunnel import CloudflareTunnelHandler
from lyoko.application.triage.dispatcher import TRIAGE_DIAGNOSE
from lyoko.application.triage.pod_crashloop import PodCrashLoopHandler
from lyoko.domain.interfaces.mcp import MCPClientInterface

logger = logging.getLogger("lyoko.application.use_cases.triage_incident")


class TriageIncidentUseCase:
    """Evaluates registered deterministic triage handlers before full multi-agent diagnosis."""

    def __init__(
        self,
        handlers: Sequence[TriageHandler] | None = None,
        mcp_client: MCPClientInterface | None = None,
        approval_manager: ApprovalManager | None = None,
        chat_manager: ChatManager | None = None,
        tracer: Any = None,
    ) -> None:
        if handlers is not None:
            self.handlers = list(handlers)
        else:
            self.handlers = [
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

    async def execute(self, state: dict[str, Any], config: RunnableConfig) -> dict[str, Any]:
        """Iterate through handlers and return early if any handler resolves the incident."""
        for handler in self.handlers:
            try:
                if handler.can_handle(state):
                    result = await handler.execute(state, config)
                    if result is not None and result.handled:
                        return result.to_state_patch()
            except Exception as exc:
                logger.warning(
                    "Triage handler %s failed: %s; falling through.",
                    handler.__class__.__name__,
                    exc,
                )
        return {"triage": TRIAGE_DIAGNOSE}
