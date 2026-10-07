"""Remediate node: executes the diagnosis plan with approval-gated tools."""

import logging
from collections.abc import Callable
from typing import Any

from langchain_core.runnables import RunnableConfig
from lyoko.application.chat_manager import ChatManager
from lyoko.application.hitl import ApprovalManager
from lyoko.application.nodes.helpers import (
    _NO_FIX_MESSAGE,
)
from lyoko.application.tool_gate import CallOutcome, ToolCallRecord
from lyoko.domain.interfaces.llm import LLMClientInterface

logger = logging.getLogger("lyoko.workflow.incident")


def _remediation_outcome(
    records: list[ToolCallRecord], summary: str, error: str | None
) -> dict[str, Any]:
    """Turn the gate's audit trail into the remediation node's state update."""
    actions = [r.to_dict() for r in records]
    denied = [r for r in records if r.outcome is CallOutcome.DENIED]
    refused = [r for r in records if r.outcome is CallOutcome.REFUSED]
    executed = [r for r in records if r.executed]

    if denied:
        action_taken = f"Remediation aborted: {denied[0].reason}"
    elif refused:
        action_taken = f"Remediation aborted: {refused[0].reason}"
    elif error is not None:
        action_taken = f"Remediation failed: {error}"
    elif not executed:
        action_taken = f"{_NO_FIX_MESSAGE}. {summary}".strip()
    else:
        action_taken = summary or "Changes applied."

    escalate = bool(denied or refused or error is not None or not executed)
    return {"action_taken": action_taken, "actions": actions, "requires_escalation": escalate}


def create_remediate_node(
    mcp_client: Any,
    llm: LLMClientInterface | None,
    supervisor: Any = None,
    approval_manager: ApprovalManager | None = None,
    chat_manager: ChatManager | None = None,
) -> Callable[[dict[str, Any], RunnableConfig], Any]:
    """Factory creating the remediate node handler."""
    from lyoko.application.use_cases.remediate_incident import RemediateIncidentUseCase

    use_case = RemediateIncidentUseCase(
        mcp_client=mcp_client,
        llm=llm,
        supervisor=supervisor,
        approval_manager=approval_manager,
        chat_manager=chat_manager,
    )

    async def remediate_node(state: dict[str, Any], config: RunnableConfig) -> dict[str, Any]:
        """Carry out the plan. State-changing tools wait for operator approval."""
        return await use_case.execute(state, config=config)

    return remediate_node
