"""Shared helper functions and constants for LYOKO workflow graph nodes."""

from typing import Any

from langchain_core.runnables import RunnableConfig
from lyoko.application.chat_manager import ChatManager
from lyoko.application.hitl import ApprovalManager
from lyoko.application.tool_gate import CallOutcome, GateMode, ToolGate
from lyoko.config import settings
from lyoko.domain.interfaces.llm import LLMClientInterface

EVENT_ALERT = "alert"
EVENT_MESSAGE = "message"

_NO_FIX_MESSAGE = "No automated fix applied (requires human inspection)"
_NO_LLM_REPLY = "Received message: '{text}'. (LLM provider not configured)"
_EXECUTED_OUTCOMES = frozenset({CallOutcome.AUTO_APPROVED.value, CallOutcome.APPROVED.value})
_MAX_SUBJECT_CHARS = 200


def format_pairs(pairs: dict[str, str]) -> str:
    return "\n".join(f"- {key}: {value}" for key, value in sorted(pairs.items())) or "- (none)"


def is_message(state: dict[str, Any]) -> bool:
    return state.get("event_type", EVENT_ALERT) == EVENT_MESSAGE


def incident_context(state: dict[str, Any]) -> str:
    if is_message(state):
        return f"Problem reported by the operator in chat:\n{state.get('text', '')}"
    return (
        f"Alert: {state.get('alert_name', 'UnknownAlert')}\n"
        f"Labels:\n{format_pairs(state.get('labels') or {})}\n"
        f"Annotations:\n{format_pairs(state.get('annotations') or {})}"
    )


def origin(state: dict[str, Any]) -> str:
    """One line telling the operator what triggered the run (shown in approval requests)."""
    if is_message(state):
        return f"Chat request: {truncate(state.get('text', ''))}"
    return f"Alert: {state.get('alert_name', 'UnknownAlert')}"


def truncate(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= _MAX_SUBJECT_CHARS else text[:_MAX_SUBJECT_CHARS] + "..."


def describe_call(record: dict[str, Any]) -> str:
    return f"`{record['tool']}` ({record['outcome'].replace('_', ' ')})"


def make_gate(
    state: dict[str, Any],
    mode: GateMode,
    approval_manager: ApprovalManager | None = None,
    chat_manager: ChatManager | None = None,
) -> ToolGate:
    alert_name = state.get("alert_name") or "event"
    event_id = state.get("event_id") or f"incident-{alert_name}"
    return ToolGate(
        mode=mode,
        read_only_patterns=settings.read_only_tools,
        auto_approved_patterns=settings.auto_approved_tools,
        event_id=event_id,
        origin=origin(state),
        session_id=state.get("session_id"),
        chat_id=state.get("chat_id") or settings.telegram_default_chat_id or "",
        approval_manager=approval_manager,
        chat_manager=chat_manager,
    )


async def run_agent(
    state: dict[str, Any],
    gate: ToolGate,
    config: RunnableConfig,
    mcp_client: Any,
    llm: LLMClientInterface | None,
    *,
    phase: str,
    system_prompt: str,
    prompt: str,
) -> str:
    """Run one tool-using agent with every tool call going through ``gate``."""
    assert llm is not None
    return await llm.chat(
        prompt=prompt,
        system_prompt=system_prompt,
        tools=mcp_client.get_langchain_tools(authorizer=gate.authorize),
        session_id=state.get("session_id"),
        trace_name=f"{phase}-agent",
        tags=[f"phase:{phase}"],
        max_steps=settings.max_agent_steps,
        parent_config=config,
    )


async def run_supervised(
    state: dict[str, Any],
    gate: ToolGate,
    config: RunnableConfig,
    mcp_client: Any,
    llm: LLMClientInterface | None,
    supervisor: Any,
    *,
    phase: str,
    prompt: str,
    system_prompt: str | None = None,
) -> str:
    """Run through the supervisor + specialists when available; otherwise fall back."""
    if supervisor is None:
        if system_prompt is None:
            raise ValueError("system_prompt is required when no supervisor is configured")
        return await run_agent(
            state,
            gate,
            config,
            mcp_client=mcp_client,
            llm=llm,
            phase=phase,
            system_prompt=system_prompt,
            prompt=prompt,
        )
    return await supervisor.coordinate(
        prompt=prompt,
        system_prompt=system_prompt,
        session_id=state.get("session_id"),
        tags=[f"phase:{phase}"],
        authorizer=gate.authorize,
        parent_config=config,
        max_steps=settings.max_agent_steps,
    )
