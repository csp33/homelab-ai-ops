"""Feedback command handling for the Telegram chat connector.

Turns a /feedback or /teach operator instruction into a persisted memory entry, extracting the
incident context from the message being replied to when present.
"""

import html
import logging
from typing import Any

from lyoko.domain.interfaces.embeddings import EmbeddingsServiceInterface
from lyoko.domain.interfaces.memory import MemoryRepositoryInterface

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

        from lyoko.application.use_cases.record_feedback import RecordFeedbackUseCase

        use_case = RecordFeedbackUseCase(
            memory_repository=self.memory_repository,
            embeddings_service=self.embeddings_service,
        )

        reply_to = getattr(msg, "reply_to_message", None)
        reply_to_text = getattr(reply_to, "text", None) if reply_to else None

        memory_id, service_name, namespace = await use_case.execute_from_chat_command(
            feedback_content=feedback_content,
            reply_to_text=reply_to_text,
        )

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
