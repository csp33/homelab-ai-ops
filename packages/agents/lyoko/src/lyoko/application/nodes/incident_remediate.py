"""Remediate node: executes the diagnosis plan with approval-gated tools."""

import logging
from collections.abc import Callable
from typing import Any

from langchain_core.runnables import RunnableConfig
from lyoko.application.chat_manager import ChatManager
from lyoko.application.hitl import ApprovalManager
from lyoko.application.incident_prompts import REMEDIATE_SYSTEM_PROMPT, parse_result
from lyoko.application.incident_status import (
    format_remediating_status,
    format_verifying_status,
)
from lyoko.application.nodes.helpers import (
    _NO_FIX_MESSAGE,
    incident_context,
    make_gate,
    run_supervised,
)
from lyoko.application.tool_gate import CallOutcome, GateMode, ToolCallRecord
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

    async def remediate_node(state: dict[str, Any], config: RunnableConfig) -> dict[str, Any]:
        """Carry out the plan. State-changing tools wait for operator approval."""
        if state.get("requires_escalation") or llm is None:
            return {"action_taken": _NO_FIX_MESSAGE, "requires_escalation": True}

        gate = make_gate(
            state,
            GateMode.APPROVAL,
            approval_manager=approval_manager,
            chat_manager=chat_manager,
            plan=state.get("plan", ""),
        )
        error: str | None = None
        summary = ""
        try:
            answer = await run_supervised(
                state,
                gate,
                config,
                mcp_client=mcp_client,
                llm=llm,
                supervisor=supervisor,
                phase="remediate",
                system_prompt=REMEDIATE_SYSTEM_PROMPT,
                prompt=(
                    f"Carry out this remediation plan.\n\n{incident_context(state)}\n\n"
                    f"Root cause: {state.get('root_cause', 'Unknown')}\n\n"
                    f"Plan:\n{state.get('plan', '')}"
                ),
            )
            summary = parse_result(answer)
        except Exception as exc:
            logger.error("Remediation failed: %s", exc, exc_info=True)
            error = str(exc)

        outcome = _remediation_outcome(gate.records, summary, error)
        progress_msg_id = state.get("progress_message_id")
        progress_chat_id = state.get("progress_chat_id")
        if chat_manager is not None and progress_msg_id and progress_chat_id:
            if not outcome.get("requires_escalation"):
                status_text = format_verifying_status(
                    state,
                    state.get("root_cause", "Unknown"),
                    outcome.get("action_taken", "Changes applied."),
                )
            else:
                status_text = format_remediating_status(
                    state,
                    state.get("root_cause", "Unknown"),
                    requires_escalation=True,
                )
            await chat_manager.edit_message(
                chat_id=progress_chat_id,
                message_id=progress_msg_id,
                text=status_text,
            )

        return outcome

    return remediate_node
