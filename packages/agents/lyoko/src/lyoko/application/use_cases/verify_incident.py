"""Use case for verifying incident resolution after remediation."""

import asyncio
import logging
from typing import Any

from langchain_core.runnables import RunnableConfig
from lyoko.application.chat_manager import ChatManager
from lyoko.application.hitl import ApprovalManager
from lyoko.application.incident_prompts import VERIFY_SYSTEM_PROMPT, parse_verdict
from lyoko.application.nodes.helpers import (
    _EXECUTED_OUTCOMES,
    describe_call,
    incident_context,
    make_gate,
    run_supervised,
    status_callback,
)
from lyoko.application.tool_gate import GateMode
from lyoko.config import settings
from lyoko.domain.interfaces.llm import LLMClientInterface
from lyoko.domain.interfaces.mcp import MCPClientInterface
from lyoko.domain.interfaces.supervisor import SupervisorInterface

logger = logging.getLogger("lyoko.application.use_cases.verify_incident")


class VerifyIncidentUseCase:
    """Verifies in read-only mode that an incident is resolved after remediation."""

    def __init__(
        self,
        mcp_client: MCPClientInterface | None,
        llm: LLMClientInterface | None,
        supervisor: SupervisorInterface | None = None,
        approval_manager: ApprovalManager | None = None,
        chat_manager: ChatManager | None = None,
    ) -> None:
        self.mcp_client = mcp_client
        self.llm = llm
        self.supervisor = supervisor
        self.approval_manager = approval_manager
        self.chat_manager = chat_manager

    async def execute(self, state: dict[str, Any], config: RunnableConfig) -> dict[str, Any]:
        """Check, read-only, that the incident is actually resolved."""
        executed = [a for a in state.get("actions", []) if a["outcome"] in _EXECUTED_OUTCOMES]
        if state.get("requires_escalation") or not executed or self.llm is None:
            return {"is_resolved": False}

        logger.info("Waiting %ss for stabilization...", settings.verification_delay_seconds)
        await asyncio.sleep(settings.verification_delay_seconds)

        gate = make_gate(
            state,
            GateMode.READ_ONLY,
            approval_manager=self.approval_manager,
            chat_manager=self.chat_manager,
            mcp_client=self.mcp_client,
        )
        changes = "\n".join(f"- {describe_call(a)} {a['arguments']}" for a in executed)
        try:
            answer = await run_supervised(
                state,
                gate,
                config,
                mcp_client=self.mcp_client,
                llm=self.llm,
                supervisor=self.supervisor,
                phase="verify",
                system_prompt=VERIFY_SYSTEM_PROMPT,
                prompt=(
                    f"Verify this incident is resolved.\n\n{incident_context(state)}\n\n"
                    f"Root cause: {state.get('root_cause', 'Unknown')}\n\n"
                    f"Changes applied:\n{changes}"
                ),
                on_status=status_callback(config),
            )
        except Exception as exc:
            logger.error("Verification failed: %s", exc, exc_info=True)
            return {"is_resolved": False, "verification": f"Verification failed: {exc}"}

        resolved, evidence = parse_verdict(answer)
        return {"is_resolved": resolved, "verification": evidence}
