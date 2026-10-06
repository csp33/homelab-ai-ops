"""Notification node for publishing incident reports and replying to operators."""

import logging
from collections.abc import Callable
from typing import Any

from lyoko.application.chat_manager import ChatManager
from lyoko.application.nodes.helpers import (
    describe_call,
    is_message,
    truncate,
)
from lyoko.config import settings

logger = logging.getLogger("lyoko.workflow.notify")


def format_incident_report(state: dict[str, Any]) -> str:
    """Build a structured Markdown incident summary from workflow state."""
    resolved = bool(state.get("is_resolved"))
    status = "✅ RESOLVED" if resolved else "🚨 ESCALATED / REQUIRES ACTION"
    lines = ["📋 **LYOKO Incident Report**", "", f"**Status:** {status}"]
    if is_message(state):
        lines.append(f"**Report:** {truncate(state.get('text', ''))}")
    else:
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

    async def notify_node(state: dict[str, Any]) -> dict[str, Any]:
        """Build the incident report. Alerts broadcast it; a message gets it as the reply."""
        summary = format_incident_report(state)
        logger.info(summary)
        if is_message(state):
            # The Telegram handler sends the reply to the message that started the incident.
            return {"reply": summary}
        if chat_manager is not None:
            progress_message_id = state.get("progress_message_id")
            progress_chat_id = state.get("progress_chat_id")
            edited = False
            if progress_message_id and progress_chat_id:
                results = await chat_manager.edit_message(
                    chat_id=progress_chat_id,
                    message_id=progress_message_id,
                    text=summary,
                )
                edited = bool(results)
            if not edited:
                chat_id = state.get("chat_id") or settings.telegram_default_chat_id or ""
                await chat_manager.broadcast_message(
                    chat_id=chat_id, text=summary, session_id=state.get("session_id")
                )
        return {}

    return notify_node
