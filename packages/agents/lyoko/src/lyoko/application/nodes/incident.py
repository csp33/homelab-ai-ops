"""Incident branch nodes (diagnose, remediate, verify) for autonomous problem resolution."""

import asyncio
import logging
from collections.abc import Callable
from typing import Any

from langchain_core.runnables import RunnableConfig
from lyoko.application.chat_manager import ChatManager
from lyoko.application.hitl import ApprovalManager
from lyoko.application.incident_prompts import (
    DIAGNOSE_SYSTEM_PROMPT,
    REMEDIATE_SYSTEM_PROMPT,
    VERIFY_SYSTEM_PROMPT,
    parse_diagnosis,
    parse_result,
    parse_verdict,
)
from lyoko.application.incident_status import (
    format_diagnosing_status,
    format_remediating_status,
    format_verifying_status,
)
from lyoko.application.nodes.helpers import (
    _EXECUTED_OUTCOMES,
    _NO_FIX_MESSAGE,
    describe_call,
    incident_context,
    is_message,
    make_gate,
    origin,
    run_supervised,
)
from lyoko.application.nodes.incident_memory import retrieve_incident_lessons
from lyoko.application.tool_gate import CallOutcome, GateMode, ToolCallRecord
from lyoko.config import settings
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


def create_diagnose_node(
    mcp_client: Any,
    llm: LLMClientInterface | None,
    supervisor: Any = None,
    approval_manager: ApprovalManager | None = None,
    chat_manager: ChatManager | None = None,
    memory_repository: Any = None,
    embeddings_service: Any = None,
) -> Callable[[dict[str, Any], RunnableConfig], Any]:
    """Factory creating the diagnose node handler."""

    async def diagnose_node(state: dict[str, Any], config: RunnableConfig) -> dict[str, Any]:
        """Investigate read-only and decide whether a fix is possible."""
        if llm is None:
            return {
                "root_cause": "Not investigated: no LLM provider is configured.",
                "requires_escalation": True,
            }

        matched_memories, lessons_context = await retrieve_incident_lessons(
            state=state,
            memory_repository=memory_repository,
            embeddings_service=embeddings_service,
        )

        logger.info("Diagnosing %s...", origin(state))
        progress_msg_id: str | None = state.get("progress_message_id")
        progress_chat_id: str | None = state.get("progress_chat_id")

        if chat_manager is not None and not is_message(state) and not progress_msg_id:
            chat_id = state.get("chat_id") or settings.telegram_default_chat_id or ""
            if chat_id:
                status_text = format_diagnosing_status(state)
                sent_list = await chat_manager.broadcast_message(
                    chat_id=chat_id,
                    text=status_text,
                    session_id=state.get("session_id"),
                )
                if sent_list:
                    progress_msg_id = sent_list[0].message_id
                    progress_chat_id = sent_list[0].chat_id

        gate = make_gate(
            state,
            GateMode.READ_ONLY,
            approval_manager=approval_manager,
            chat_manager=chat_manager,
        )
        try:
            prompt_content = f"Investigate this.\n\n{incident_context(state)}{lessons_context}"
            answer = await run_supervised(
                state,
                gate,
                config,
                mcp_client=mcp_client,
                llm=llm,
                supervisor=supervisor,
                phase="diagnose",
                system_prompt=DIAGNOSE_SYSTEM_PROMPT,
                prompt=prompt_content,
            )
        except Exception as exc:
            logger.error("Investigation failed: %s", exc, exc_info=True)
            return {"root_cause": f"Investigation failed: {exc}", "requires_escalation": True}

        diagnosis = parse_diagnosis(answer)
        if chat_manager is not None and progress_msg_id and progress_chat_id:
            status_text = format_remediating_status(
                state,
                diagnosis.root_cause,
                requires_escalation=not diagnosis.actionable,
            )
            await chat_manager.edit_message(
                chat_id=progress_chat_id,
                message_id=progress_msg_id,
                text=status_text,
            )

        return {
            "root_cause": diagnosis.root_cause,
            "plan": diagnosis.plan,
            "requires_escalation": not diagnosis.actionable,
            "matched_memories": matched_memories,
            "lessons_context": lessons_context,
            "progress_message_id": progress_msg_id,
            "progress_chat_id": progress_chat_id,
        }

    return diagnose_node


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


def create_verify_node(
    mcp_client: Any,
    llm: LLMClientInterface | None,
    supervisor: Any = None,
    approval_manager: ApprovalManager | None = None,
    chat_manager: ChatManager | None = None,
) -> Callable[[dict[str, Any], RunnableConfig], Any]:
    """Factory creating the verify node handler."""

    async def verify_node(state: dict[str, Any], config: RunnableConfig) -> dict[str, Any]:
        """Check, read-only, that the incident is actually resolved."""
        executed = [a for a in state.get("actions", []) if a["outcome"] in _EXECUTED_OUTCOMES]
        if state.get("requires_escalation") or not executed or llm is None:
            return {"is_resolved": False}

        logger.info("Waiting %ss for stabilization...", settings.verification_delay_seconds)
        await asyncio.sleep(settings.verification_delay_seconds)

        gate = make_gate(
            state,
            GateMode.READ_ONLY,
            approval_manager=approval_manager,
            chat_manager=chat_manager,
        )
        changes = "\n".join(f"- {describe_call(a)} {a['arguments']}" for a in executed)
        try:
            answer = await run_supervised(
                state,
                gate,
                config,
                mcp_client=mcp_client,
                llm=llm,
                supervisor=supervisor,
                phase="verify",
                system_prompt=VERIFY_SYSTEM_PROMPT,
                prompt=(
                    f"Verify this incident is resolved.\n\n{incident_context(state)}\n\n"
                    f"Root cause: {state.get('root_cause', 'Unknown')}\n\n"
                    f"Changes applied:\n{changes}"
                ),
            )
        except Exception as exc:
            logger.error("Verification failed: %s", exc, exc_info=True)
            return {"is_resolved": False, "verification": f"Verification failed: {exc}"}

        resolved, evidence = parse_verdict(answer)
        return {"is_resolved": resolved, "verification": evidence}

    return verify_node
