"""Reply delivery for inbound Telegram messages.

Sends a handler's reply back to the originating chat, redirecting to the linked discussion group
for channel posts and degrading from HTML to plain text when Telegram rejects the markup.
"""

import logging
from typing import Any

from lyoko.infrastructure.chat.formatting import markdown_to_telegram_html

logger = logging.getLogger("lyoko.chat.telegram")


class TelegramReplyMixin:
    """Deliver replies with discussion-group redirect and HTML fallback."""

    discussion_group_id: str | None
    _channel_to_discussion: dict[tuple[str, int], int]

    def _resolve_reply_target(
        self,
        msg: Any,
        chat_id: str,
        chat_type: str,
        message_thread_id: Any,
    ) -> tuple[str, Any, Any]:
        """Return (target_chat_id, target_reply_to_message_id, target_thread_id).

        A channel post with a linked discussion group is answered in that group's thread instead
        of creating a new opener post in the channel. The channel post's ``message_thread_id`` is
        the topic id in the discussion group, so it is the correct thread target.
        """
        target_chat_id = chat_id
        target_reply_id = msg.message_id
        target_thread_id = message_thread_id

        if chat_type == "channel" and self.discussion_group_id:
            disc_msg_id = self._channel_to_discussion.get((str(chat_id), msg.message_id))
            target_chat_id = self.discussion_group_id
            target_thread_id = message_thread_id if message_thread_id is not None else disc_msg_id
            target_reply_id = disc_msg_id if disc_msg_id else msg.message_id
            logger.info(
                "Redirecting reply for channel post %s to discussion group %s "
                "with reply_to=%s, thread=%s",
                msg.message_id,
                self.discussion_group_id,
                target_reply_id,
                target_thread_id,
            )
        return target_chat_id, target_reply_id, target_thread_id

    async def _reply_to_chat(
        self,
        msg: Any,
        reply: str,
        chat_id: str,
        chat_type: str,
        message_thread_id: Any,
    ) -> None:
        """Send ``reply`` back to the originating message, threading it correctly."""
        formatted_reply = markdown_to_telegram_html(reply)
        target_chat_id, target_reply_id, target_thread_id = self._resolve_reply_target(
            msg, chat_id, chat_type, message_thread_id
        )

        if target_chat_id != chat_id:
            try:
                await self.send_message(
                    chat_id=target_chat_id,
                    text=reply,
                    reply_to_message_id=target_reply_id,
                    message_thread_id=target_thread_id,
                    parse_mode="HTML",
                )
            except Exception as disc_err:
                logger.warning(
                    "Failed to reply to discussion group %s, falling back to channel reply: %s",
                    target_chat_id,
                    disc_err,
                )
                await msg.reply_text(
                    formatted_reply,
                    parse_mode="HTML",
                    reply_to_message_id=msg.message_id,
                    message_thread_id=message_thread_id,
                    allow_sending_without_reply=True,
                )
        else:
            try:
                await msg.reply_text(
                    formatted_reply,
                    parse_mode="HTML",
                    reply_to_message_id=msg.message_id,
                    message_thread_id=message_thread_id,
                    allow_sending_without_reply=True,
                )
            except Exception as html_err:
                logger.warning("Failed to reply with HTML, falling back: %s", html_err)
                try:
                    await msg.reply_text(
                        reply,
                        reply_to_message_id=msg.message_id,
                        message_thread_id=message_thread_id,
                        allow_sending_without_reply=True,
                    )
                except Exception:
                    await self.send_message(
                        chat_id=chat_id,
                        text=reply,
                        reply_to_message_id=msg.message_id,
                        message_thread_id=message_thread_id,
                    )
