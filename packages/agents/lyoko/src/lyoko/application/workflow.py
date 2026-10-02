"""LangGraph StateGraph of LYOKO: one graph, two branches.

Every event enters at ``route`` and takes one of two branches::

    START -> route -+-> chat                                      -> END
                    +-> diagnose -> remediate -> verify -> notify -> END

* ``chat`` answers an operator message, or carries out a request, in a single tool-using run.
* The incident branch investigates, fixes, verifies and reports. Alertmanager alerts always
  take it. A Telegram message takes it when the router decides the operator is reporting
  something broken, and takes ``chat`` otherwise.

The agent runs use the homelab-mcp gateway, so nothing here is specific to Kubernetes: the agent
discovers whatever tools the gateway exposes.

Safety does not rely on the agent's judgement. Every run gets a ``ToolGate`` built from one
policy for both branches: read-only tools run, auto-approved tools run, and everything else waits
for the operator. Diagnosis and verification are stricter still and cannot change anything.

Every agent run receives the node's run config, so one event produces one trace in which each
node and each agent run is a named child span.
"""

import asyncio
import logging
from typing import Any, TypedDict

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from lyoko.application.chat_manager import ChatManager
from lyoko.application.chat_prompts import CHAT_SYSTEM_PROMPT
from lyoko.application.hitl import ApprovalManager
from lyoko.application.incident_prompts import (
    DIAGNOSE_SYSTEM_PROMPT,
    REMEDIATE_SYSTEM_PROMPT,
    VERIFY_SYSTEM_PROMPT,
    parse_diagnosis,
    parse_result,
    parse_verdict,
)
from lyoko.application.router import ROUTER_SYSTEM_PROMPT, Route, parse_route
from lyoko.application.tool_gate import CallOutcome, GateMode, ToolCallRecord, ToolGate
from lyoko.config import settings
from lyoko.domain.interfaces.llm import LLMClientInterface

logger = logging.getLogger("lyoko.workflow")

EVENT_ALERT = "alert"
EVENT_MESSAGE = "message"

_NO_FIX_MESSAGE = "No automated fix applied (requires human inspection)"
_NO_LLM_REPLY = "Received message: '{text}'. (LLM provider not configured)"
_EXECUTED_OUTCOMES = frozenset({CallOutcome.AUTO_APPROVED.value, CallOutcome.APPROVED.value})
_MAX_SUBJECT_CHARS = 200


class LyokoState(TypedDict, total=False):
    # What happened. ``event_type`` is "alert" (the default) or "message".
    event_type: str
    event_id: str
    """Short id of this run. It prefixes approval ids, which end up in Telegram callback data."""
    session_id: str
    """Observability session the run belongs to (a chat session, or the incident)."""
    chat_id: str
    text: str
    """The operator's message, for ``event_type == "message"``."""
    alert_name: str
    labels: dict[str, str]
    annotations: dict[str, str]

    # Routing and chat branch
    route: str
    reply: str
    """The text to send back to the operator, set by ``chat`` and, for messages, by ``notify``."""

    # Incident branch
    root_cause: str
    plan: str
    action_taken: str
    actions: list[dict[str, Any]]
    verification: str
    is_resolved: bool
    requires_escalation: bool


def _format_pairs(pairs: dict[str, str]) -> str:
    return "\n".join(f"- {key}: {value}" for key, value in sorted(pairs.items())) or "- (none)"


def _is_message(state: LyokoState) -> bool:
    return state.get("event_type", EVENT_ALERT) == EVENT_MESSAGE


def _incident_context(state: LyokoState) -> str:
    if _is_message(state):
        return f"Problem reported by the operator in chat:\n{state.get('text', '')}"
    return (
        f"Alert: {state.get('alert_name', 'UnknownAlert')}\n"
        f"Labels:\n{_format_pairs(state.get('labels') or {})}\n"
        f"Annotations:\n{_format_pairs(state.get('annotations') or {})}"
    )


def _origin(state: LyokoState) -> str:
    """One line telling the operator what triggered the run (shown in approval requests)."""
    if _is_message(state):
        return f"Chat request: {_truncate(state.get('text', ''))}"
    return f"Alert: {state.get('alert_name', 'UnknownAlert')}"


def _truncate(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= _MAX_SUBJECT_CHARS else text[:_MAX_SUBJECT_CHARS] + "..."


def _describe_call(record: dict[str, Any]) -> str:
    return f"`{record['tool']}` ({record['outcome'].replace('_', ' ')})"


def create_lyoko_graph(
    mcp_client: Any,
    approval_manager: ApprovalManager | None = None,
    chat_manager: ChatManager | None = None,
    checkpointer: Any = None,
    llm: LLMClientInterface | None = None,
) -> Any:
    """Build the LangGraph StateGraph that routes, answers, investigates and remediates."""

    def make_gate(state: LyokoState, mode: GateMode) -> ToolGate:
        alert_name = state.get("alert_name") or "event"
        event_id = state.get("event_id") or f"incident-{alert_name}"
        return ToolGate(
            mode=mode,
            read_only_patterns=settings.read_only_tools,
            auto_approved_patterns=settings.auto_approved_tools,
            event_id=event_id,
            origin=_origin(state),
            session_id=state.get("session_id"),
            chat_id=state.get("chat_id") or settings.telegram_default_chat_id or "",
            approval_manager=approval_manager,
            chat_manager=chat_manager,
        )

    async def run_agent(
        state: LyokoState,
        gate: ToolGate,
        config: RunnableConfig,
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

    # ------------------------------------------------------------------
    # Routing
    # ------------------------------------------------------------------

    async def route_node(state: LyokoState, config: RunnableConfig) -> dict[str, Any]:
        """Alerts are incidents. For a message, the LLM decides between chat and incident."""
        if not _is_message(state):
            return {"route": Route.INCIDENT.value}
        if llm is None:
            return {"route": Route.CHAT.value}

        try:
            answer = await llm.chat(
                prompt=state.get("text", ""),
                system_prompt=ROUTER_SYSTEM_PROMPT,
                trace_name="route-llm",
                tags=["phase:route"],
                parent_config=config,
            )
        except Exception as exc:
            logger.warning("Routing failed, answering in chat: %s", exc)
            return {"route": Route.CHAT.value}

        route = parse_route(answer)
        logger.info("Routed message to %s", route.value)
        return {"route": route.value}

    def choose_branch(state: LyokoState) -> str:
        return "diagnose" if state.get("route") == Route.INCIDENT.value else "chat"

    # ------------------------------------------------------------------
    # Chat branch
    # ------------------------------------------------------------------

    async def chat_node(state: LyokoState, config: RunnableConfig) -> dict[str, Any]:
        """Answer the operator. Changes go through the gate: trusted ones run, others ask."""
        text = state.get("text", "")
        if llm is None:
            return {"reply": _NO_LLM_REPLY.format(text=text)}

        gate = make_gate(state, GateMode.APPROVAL)
        try:
            answer = await run_agent(
                state,
                gate,
                config,
                phase="chat",
                system_prompt=CHAT_SYSTEM_PROMPT,
                prompt=text,
            )
        except Exception as exc:
            logger.error("Failed to generate LLM response: %s", exc)
            return {"reply": f"⚠️ Error processing your question: {exc}"}
        return {"reply": answer, "actions": [r.to_dict() for r in gate.records]}

    # ------------------------------------------------------------------
    # Incident branch
    # ------------------------------------------------------------------

    async def diagnose_node(state: LyokoState, config: RunnableConfig) -> dict[str, Any]:
        """Investigate read-only and decide whether a fix is possible."""
        if llm is None:
            return {
                "root_cause": "Not investigated: no LLM provider is configured.",
                "requires_escalation": True,
            }

        logger.info("Diagnosing %s...", _origin(state))
        gate = make_gate(state, GateMode.READ_ONLY)
        try:
            answer = await run_agent(
                state,
                gate,
                config,
                phase="diagnose",
                system_prompt=DIAGNOSE_SYSTEM_PROMPT,
                prompt=f"Investigate this.\n\n{_incident_context(state)}",
            )
        except Exception as exc:
            logger.error("Investigation failed: %s", exc, exc_info=True)
            return {"root_cause": f"Investigation failed: {exc}", "requires_escalation": True}

        diagnosis = parse_diagnosis(answer)
        return {
            "root_cause": diagnosis.root_cause,
            "plan": diagnosis.plan,
            "requires_escalation": not diagnosis.actionable,
        }

    async def remediate_node(state: LyokoState, config: RunnableConfig) -> dict[str, Any]:
        """Carry out the plan. State-changing tools wait for operator approval."""
        if state.get("requires_escalation") or llm is None:
            return {"action_taken": _NO_FIX_MESSAGE, "requires_escalation": True}

        gate = make_gate(state, GateMode.APPROVAL)
        error: str | None = None
        summary = ""
        try:
            answer = await run_agent(
                state,
                gate,
                config,
                phase="remediate",
                system_prompt=REMEDIATE_SYSTEM_PROMPT,
                prompt=(
                    f"Fix this incident.\n\n{_incident_context(state)}\n\n"
                    f"Root cause: {state.get('root_cause', 'Unknown')}\n\n"
                    f"Plan:\n{state.get('plan', '')}"
                ),
            )
            summary = parse_result(answer)
        except Exception as exc:
            logger.error("Remediation failed: %s", exc, exc_info=True)
            error = str(exc)

        return _remediation_outcome(gate.records, summary, error)

    async def verify_node(state: LyokoState, config: RunnableConfig) -> dict[str, Any]:
        """Check, read-only, that the incident is actually resolved."""
        executed = [a for a in state.get("actions", []) if a["outcome"] in _EXECUTED_OUTCOMES]
        if state.get("requires_escalation") or not executed or llm is None:
            return {"is_resolved": False}

        logger.info("Waiting %ss for stabilization...", settings.verification_delay_seconds)
        await asyncio.sleep(settings.verification_delay_seconds)

        gate = make_gate(state, GateMode.READ_ONLY)
        changes = "\n".join(f"- {_describe_call(a)} {a['arguments']}" for a in executed)
        try:
            answer = await run_agent(
                state,
                gate,
                config,
                phase="verify",
                system_prompt=VERIFY_SYSTEM_PROMPT,
                prompt=(
                    f"Verify this incident is resolved.\n\n{_incident_context(state)}\n\n"
                    f"Root cause: {state.get('root_cause', 'Unknown')}\n\n"
                    f"Changes applied:\n{changes}"
                ),
            )
        except Exception as exc:
            logger.error("Verification failed: %s", exc, exc_info=True)
            return {"is_resolved": False, "verification": f"Verification failed: {exc}"}

        resolved, evidence = parse_verdict(answer)
        return {"is_resolved": resolved, "verification": evidence}

    async def notify_node(state: LyokoState) -> dict[str, Any]:
        """Build the incident report. Alerts broadcast it; a message gets it as the reply."""
        status = "RESOLVED" if state.get("is_resolved") else "ESCALATED / REQUIRES ACTION"
        lines = ["📋 *[LYOKO Incident Report]*", "", f"• *Status:* {status}"]
        if _is_message(state):
            lines.append(f"• *Report:* {_truncate(state.get('text', ''))}")
        else:
            labels = state.get("labels") or {}
            target = ", ".join(f"{k}={labels[k]}" for k in sorted(labels) if k != "alertname")
            lines.append(f"• *Alert:* {state.get('alert_name', '')}")
            if target:
                lines.append(f"• *Target:* {target}")
        lines.append(f"• *Root Cause:* {state.get('root_cause', 'Unknown')}")
        lines.append(f"• *Action Taken:* {state.get('action_taken', 'None')}")
        actions = state.get("actions") or []
        if actions:
            lines.append("• *Tool Calls:* " + ", ".join(_describe_call(a) for a in actions))
        if state.get("verification"):
            lines.append(f"• *Verification:* {state['verification']}")
        summary = "\n".join(lines)

        logger.info(summary)
        if _is_message(state):
            # The Telegram handler sends the reply to the message that started the incident.
            return {"reply": summary}
        if chat_manager is not None:
            chat_id = state.get("chat_id") or settings.telegram_default_chat_id or ""
            await chat_manager.broadcast_message(
                chat_id=chat_id, text=summary, session_id=state.get("session_id")
            )
        return {}

    workflow = StateGraph(LyokoState)
    workflow.add_node("route", route_node)
    workflow.add_node("chat", chat_node)
    workflow.add_node("diagnose", diagnose_node)
    workflow.add_node("remediate", remediate_node)
    workflow.add_node("verify", verify_node)
    workflow.add_node("notify", notify_node)

    workflow.add_edge(START, "route")
    workflow.add_conditional_edges("route", choose_branch, {"chat": "chat", "diagnose": "diagnose"})
    workflow.add_edge("chat", END)
    workflow.add_edge("diagnose", "remediate")
    workflow.add_edge("remediate", "verify")
    workflow.add_edge("verify", "notify")
    workflow.add_edge("notify", END)

    return workflow.compile(checkpointer=checkpointer)


def _remediation_outcome(
    records: list[ToolCallRecord], summary: str, error: str | None
) -> dict[str, Any]:
    """Turn the gate's audit trail into the remediation node's state update.

    The report is built from what the gate actually allowed, not from the agent's own claims.
    """
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
