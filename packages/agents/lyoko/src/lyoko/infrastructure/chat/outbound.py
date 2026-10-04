"""Outbound Telegram operations mixed into the Telegram chat connector.

These methods send, edit, and request approval; they rely on ``self._app`` and
``self.default_chat_id`` provided by the concrete connector.
"""

import html
import logging
from typing import Any

from lyoko.domain.models.chat import ApprovalRequest, SentMessage
from lyoko.infrastructure.chat.formatting import markdown_to_telegram_html
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

logger = logging.getLogger("lyoko.chat.telegram")


def _to_sent_message(result: object, fallback_chat_id: str) -> SentMessage | None:
    """Convert a python-telegram-bot ``Message`` into a domain ``SentMessage`` reference."""
    message_id = getattr(result, "message_id", None)
    if not isinstance(message_id, int) or isinstance(message_id, bool):
        return None
    chat_id = getattr(result, "chat_id", None)
    if not isinstance(chat_id, (int, str)) or isinstance(chat_id, bool):
        chat_id = fallback_chat_id
    return SentMessage(chat_id=str(chat_id), message_id=str(message_id))


class TelegramOutboundMixin:
    """Send, edit, and request approval over a running Telegram application."""

    _app: Any
    default_chat_id: str | None

    async def send_message(
        self,
        chat_id: str,
        text: str,
        reply_to_message_id: str | int | None = None,
        message_thread_id: str | int | None = None,
        parse_mode: str = "HTML",
    ) -> SentMessage | None:
        """Send proactive text message to specific chat, group, or channel."""
        if not self._app or not self._app.bot:
            return None
        target = chat_id or self.default_chat_id
        if not target:
            return None

        msg_id = int(reply_to_message_id) if reply_to_message_id is not None else None
        thread_id = int(message_thread_id) if message_thread_id is not None else None

        if parse_mode == "HTML":
            formatted = markdown_to_telegram_html(text)
            try:
                sent = await self._app.bot.send_message(
                    chat_id=target,
                    text=formatted,
                    parse_mode="HTML",
                    reply_to_message_id=msg_id,
                    message_thread_id=thread_id,
                    allow_sending_without_reply=True,
                )
                return _to_sent_message(sent, str(target))
            except Exception as exc:
                logger.warning(
                    "Failed to send HTML formatted message to Telegram, falling back: %s", exc
                )

        try:
            sent = await self._app.bot.send_message(
                chat_id=target,
                text=text,
                parse_mode=parse_mode if parse_mode != "HTML" else None,
                reply_to_message_id=msg_id,
                message_thread_id=thread_id,
                allow_sending_without_reply=True,
            )
        except Exception:
            sent = await self._app.bot.send_message(
                chat_id=target,
                text=text,
                reply_to_message_id=msg_id,
                message_thread_id=thread_id,
                allow_sending_without_reply=True,
            )
        return _to_sent_message(sent, str(target))

    async def edit_message(
        self,
        chat_id: str,
        message_id: str | int,
        text: str,
        parse_mode: str = "HTML",
    ) -> SentMessage | None:
        """Edit an existing proactive text message in a chat, group, or channel."""
        if not self._app or not self._app.bot:
            return None
        target = chat_id or self.default_chat_id
        if not target or message_id is None:
            return None

        try:
            msg_id = int(message_id)
        except (ValueError, TypeError):
            return None

        if parse_mode == "HTML":
            formatted = markdown_to_telegram_html(text)
            try:
                sent = await self._app.bot.edit_message_text(
                    chat_id=target,
                    message_id=msg_id,
                    text=formatted,
                    parse_mode="HTML",
                )
                return _to_sent_message(sent, str(target)) or SentMessage(
                    chat_id=str(target), message_id=str(msg_id)
                )
            except Exception as exc:
                logger.warning(
                    "Failed to edit HTML formatted message in Telegram, falling back: %s", exc
                )

        try:
            sent = await self._app.bot.edit_message_text(
                chat_id=target,
                message_id=msg_id,
                text=text,
                parse_mode=parse_mode if parse_mode != "HTML" else None,
            )
        except Exception as exc:
            logger.debug("Failed to edit plain message in Telegram: %s", exc)
            return None
        return _to_sent_message(sent, str(target)) or SentMessage(
            chat_id=str(target), message_id=str(msg_id)
        )

    async def send_approval_request(
        self, request: ApprovalRequest, message_thread_id: str | int | None = None
    ) -> SentMessage | None:
        """Send interactive approval prompt with inline action buttons to chat or channel."""
        if not self._app or not self._app.bot:
            return None
        target = request.chat_id or self.default_chat_id
        if not target:
            return None

        thread_id = int(message_thread_id) if message_thread_id is not None else None

        buttons = []
        for act in request.actions:
            cb_data = f"{act.action_id}:{request.incident_id}"
            buttons.append(InlineKeyboardButton(text=act.label, callback_data=cb_data))

        keyboard = InlineKeyboardMarkup([buttons]) if buttons else None
        text = f"🚨 <b>[APPROVAL REQUIRED]</b>\n\n<b>{html.escape(request.title)}</b>\n\n{markdown_to_telegram_html(request.details)}"
        try:
            sent = await self._app.bot.send_message(
                chat_id=target,
                text=text,
                reply_markup=keyboard,
                parse_mode="HTML",
                message_thread_id=thread_id,
            )
        except Exception as exc:
            logger.warning("Failed to send approval request in HTML, falling back: %s", exc)
            plain_text = f"🚨 [APPROVAL REQUIRED]\n\n{request.title}\n\n{request.details}"
            sent = await self._app.bot.send_message(
                chat_id=target,
                text=plain_text,
                reply_markup=keyboard,
                message_thread_id=thread_id,
            )
        return _to_sent_message(sent, str(target))
