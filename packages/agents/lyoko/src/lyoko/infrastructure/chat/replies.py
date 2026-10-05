"""Reply delivery for inbound Telegram messages.

Sends a handler's reply back to the originating chat, redirecting to the linked discussion group
for channel posts and degrading from HTML to plain text when Telegram rejects the markup.
"""

import asyncio
import logging
from typing import Any

from lyoko.infrastructure.chat.formatting import markdown_to_telegram_html

logger = logging.getLogger("lyoko.chat.telegram")


class TelegramReplyMixin:
    """Deliver replies with discussion-group redirect and HTML fallback."""

    discussion_group_id: str | None
    discussion_mapping_timeout: float
    discussion_mapping_interval: float
    _channel_to_discussion: dict[tuple[str, int], int]

    async def _await_discussion_mapping(
        self,
        chat_id: str,
        message_id: int,
        timeout: float | None = None,
        interval: float | None = None,
    ) -> bool:
        """Wait for the automatic forward that links a channel post to its discussion message.

        A channel post and its automatic forward into the linked discussion group arrive as two
        separate updates, and the post can win the race. Without the mapping the reply cannot be
        threaded under the alert and lands as a stray message in the group's general topic. Give
        the forward a bounded moment to land before resolving the reply target.
        """
        key = (str(chat_id), int(message_id))
        if key in self._channel_to_discussion:
            logger.info(
                "Discussion mapping already present for channel post %s -> %s.",
                key,
                self._channel_to_discussion[key],
            )
            return True

        wait = self.discussion_mapping_timeout if timeout is None else timeout
        step = self.discussion_mapping_interval if interval is None else interval
        loop = asyncio.get_event_loop()
        deadline = loop.time() + wait
        while loop.time() < deadline:
            await asyncio.sleep(step)
            if key in self._channel_to_discussion:
                logger.info(
                    "Discussion mapping arrived for channel post %s -> %s.",
                    key,
                    self._channel_to_discussion[key],
                )
                return True

        logger.warning(
            "No discussion message for channel post %s after %.1fs; replying without a thread.",
            key,
            wait,
        )
        return False

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
        logger.info(
            "Direct reply fallback: to chat=%s reply_to=%s thread=%s (origin chat=%s type=%s).",
            target_chat_id,
            target_reply_id,
            target_thread_id,
            chat_id,
            chat_type,
        )

        if target_chat_id != chat_id:
            try:
                sent = await self.send_message(
                    chat_id=target_chat_id,
                    text=reply,
                    reply_to_message_id=target_reply_id,
                    message_thread_id=target_thread_id,
                    parse_mode="HTML",
                )
                logger.info(
                    "Direct reply sent to discussion group %s -> message_id=%s.",
                    target_chat_id,
                    getattr(sent, "message_id", None),
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
                logger.info("Direct reply sent as a channel reply for msg %s.", msg.message_id)
        else:
            try:
                await msg.reply_text(
                    formatted_reply,
                    parse_mode="HTML",
                    reply_to_message_id=msg.message_id,
                    message_thread_id=message_thread_id,
                    allow_sending_without_reply=True,
                )
                logger.info("Direct reply sent in chat %s for msg %s.", chat_id, msg.message_id)
            except Exception as html_err:
                logger.warning("Failed to reply with HTML, falling back: %s", html_err)
                try:
                    await msg.reply_text(
                        reply,
                        reply_to_message_id=msg.message_id,
                        message_thread_id=message_thread_id,
                        allow_sending_without_reply=True,
                    )
                    logger.info(
                        "Direct plain reply sent in chat %s for msg %s.", chat_id, msg.message_id
                    )
                except Exception:
                    logger.warning(
                        "msg.reply_text failed in chat %s; retrying via send_message.", chat_id
                    )
                    sent = await self.send_message(
                        chat_id=chat_id,
                        text=reply,
                        reply_to_message_id=msg.message_id,
                        message_thread_id=message_thread_id,
                    )
                    logger.info(
                        "Direct reply sent via send_message in chat %s -> message_id=%s.",
                        chat_id,
                        getattr(sent, "message_id", None),
                    )
