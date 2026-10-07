"""Notification node for publishing incident reports and replying to operators."""

import logging
from collections.abc import Callable
from typing import Any

from lyoko.application.chat_manager import ChatManager
from lyoko.application.nodes.helpers import (
    describe_call,
    is_message,
)

logger = logging.getLogger("lyoko.workflow.notify")


def format_incident_report(state: dict[str, Any]) -> str:
    """Build a structured Markdown incident summary from workflow state."""
    resolved = bool(state.get("is_resolved"))
    status = "✅ RESOLVED" if resolved else "🚨 ESCALATED / REQUIRES ACTION"
    lines = ["📋 **LYOKO Incident Report**", "", f"**Status:** {status}"]
    if not is_message(state):
        labels = state.get("labels") or {}
        target = ", ".join(f"{k}={labels[k]}" for k in sorted(labels) if k != "alertname")
        lines.append(f"**Alert:** {state.get('alert_name', '')}")
        if target:
            lines.append(f"**Target:** {target}")
    lines.append(f"**Root Cause:** {state.get('root_cause', 'Unknown')}")
    lines.append(f"**Action Taken:** {state.get('action_taken', 'None')}")
    if state.get("matched_memories"):
        lines.append(f"**Memories Applied:** {len(state['matched_memories'])}")
    actions = state.get("actions") or []
    if actions:
        lines.append("**Tool Calls:** " + ", ".join(describe_call(a) for a in actions))
    if state.get("verification"):
        lines.append(f"**Verification:** {state['verification']}")
    return "\n".join(lines)


def create_notify_node(chat_manager: ChatManager | None = None) -> Callable[[dict[str, Any]], Any]:
    """Factory creating the notify node handler."""
    from lyoko.application.use_cases.notify_report import NotifyIncidentReportUseCase

    use_case = NotifyIncidentReportUseCase(chat_manager=chat_manager)

    async def notify_node(state: dict[str, Any]) -> dict[str, Any]:
        """Build the incident report. Alerts broadcast it; a message gets it as the reply."""
        return await use_case.execute(state)

    return notify_node
