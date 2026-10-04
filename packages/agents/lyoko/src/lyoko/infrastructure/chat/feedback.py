"""Feedback command handling for the Telegram chat connector.

Turns a /feedback or /teach operator instruction into a persisted memory entry, extracting the
incident context from the message being replied to when present.
"""

import html
import logging
import re
from typing import Any

from lyoko.domain.interfaces.embeddings import EmbeddingsServiceInterface
from lyoko.domain.interfaces.memory import MemoryRepositoryInterface
from lyoko.domain.models.memory import MemoryEntry

logger = logging.getLogger("lyoko.chat.telegram")


class TelegramFeedbackMixin:
    """Persist operator feedback and taught rules into semantic memory."""

    memory_repository: MemoryRepositoryInterface | None
    embeddings_service: EmbeddingsServiceInterface | None

    async def _handle_feedback_command(self, msg: Any, text: str) -> None:
        """Process /feedback or /teach operator instruction and persist to PostgreSQL."""
        message_thread_id = getattr(msg, "message_thread_id", None)
        feedback_content = text.removeprefix("/feedback").removeprefix("/teach").strip()
        if not feedback_content:
            help_text = (
                "ℹ️ <b>Feedback usage:</b>\n"
                "<code>/feedback &lt;rule or instruction for LYOKO&gt;</code>\n\n"
                "<i>Example:</i> <code>/feedback For influxdb do not increase RAM, compact logs first</code>\n"
                "<i>Tip:</i> Reply to any incident report with <code>/feedback &lt;rule&gt;</code> to automatically associate it with that pod/service."
            )
            await msg.reply_text(
                help_text,
                parse_mode="HTML",
                reply_to_message_id=msg.message_id,
                message_thread_id=message_thread_id,
                allow_sending_without_reply=True,
            )
            return

        if not self.memory_repository:
            await msg.reply_text(
                "⚠️ The persistent memory database (PostgreSQL) is not available.",
                reply_to_message_id=msg.message_id,
                message_thread_id=message_thread_id,
                allow_sending_without_reply=True,
            )
            return

        # Extract context if replying to an incident alert/report
        namespace = "default"
        service_name = "general"
        alert_name = "OperatorRule"
        incident_pattern = feedback_content

        reply_to = getattr(msg, "reply_to_message", None)
        if reply_to and getattr(reply_to, "text", None):
            quoted_text = reply_to.text
            ns_match = re.search(r"Namespace:?\s*`?([a-zA-Z0-9_\-]+)`?", quoted_text, re.IGNORECASE)
            pod_match = re.search(r"Pod:?\s*`?([a-zA-Z0-9_\-]+)`?", quoted_text, re.IGNORECASE)
            alert_match = re.search(r"Alert:?\s*`?([a-zA-Z0-9_\-]+)`?", quoted_text, re.IGNORECASE)

            if ns_match:
                namespace = ns_match.group(1)
            if pod_match:
                pod_name = pod_match.group(1)
                service_name = pod_name.rsplit("-", 2)[0]
            if alert_match:
                alert_name = alert_match.group(1)
            incident_pattern = f"Context: {quoted_text[:200]}..."

        embedding = None
        if self.embeddings_service:
            text_to_embed = (
                f"{alert_name} {service_name} {namespace} {incident_pattern} {feedback_content}"
            )
            embedding = await self.embeddings_service.embed_text(text_to_embed)

        entry = MemoryEntry(
            namespace=namespace,
            service_name=service_name,
            alert_name=alert_name,
            incident_pattern=incident_pattern,
            operator_feedback=feedback_content,
            action_rule=feedback_content,
        )

        memory_id = await self.memory_repository.save_memory(entry, embedding=embedding)
        success_msg = (
            f"🧠 <b>Rule learned and stored in PostgreSQL</b> (ID: <code>{memory_id}</code>)\n\n"
            f"• <b>Service:</b> <code>{html.escape(service_name)}</code> ({html.escape(namespace)})\n"
            f"• <b>Rule:</b> <i>{html.escape(feedback_content)}</i>\n\n"
            f"LYOKO will apply this semantic guideline in future incidents."
        )
        await msg.reply_text(
            success_msg,
            parse_mode="HTML",
            reply_to_message_id=msg.message_id,
            message_thread_id=message_thread_id,
            allow_sending_without_reply=True,
        )
