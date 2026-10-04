"""Inbound Telegram message handling mixed into the Telegram chat connector.

Turns an incoming text message or channel post into a domain ``IncomingMessage``, authorizes it,
shows typing/streaming feedback, and dispatches it to the registered message handlers.
"""

import asyncio
import contextlib
import inspect
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from lyoko.domain.models.chat import ChatUser, IncomingMessage
from lyoko.infrastructure.chat.streamer import TelegramDraftStreamer
from telegram import Update
from telegram.ext import ContextTypes

logger = logging.getLogger("lyoko.chat.telegram")


class TelegramInboundMixin:
    """Handle incoming Telegram messages and dispatch them to domain handlers."""

    _app: Any
    _message_handlers: list[Callable[[IncomingMessage], Awaitable[str | None]]]
    _active_streamers: dict[tuple[str, int], TelegramDraftStreamer]

    async def _handle_telegram_message(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle incoming text messages and channel posts from Telegram."""
        msg = getattr(update, "message", None) or getattr(update, "effective_message", None)
        if not msg or not getattr(msg, "text", None):
            return

        chat = getattr(update, "effective_chat", None) or getattr(msg, "chat", None)
        chat_type = str(getattr(chat, "type", "")) if chat else ""
        chat_id = (
            str(chat.id)
            if chat and getattr(chat, "id", None) is not None and not hasattr(chat.id, "_mock_name")
            else ""
        )
        logger.info(
            "_handle_telegram_message: msg_id=%s, chat_type=%s, chat_id=%s, "
            "is_automatic_forward=%s, text=%r",
            getattr(msg, "message_id", None),
            chat_type,
            chat_id,
            getattr(msg, "is_automatic_forward", None),
            (str(msg.text).strip()[:80] if msg.text else None),
        )

        # Automatic forward from channel to discussion group - record the mapping so replies to
        # the original channel post can be threaded here, then do not process it as a user command.
        if getattr(msg, "is_automatic_forward", None) is True:
            self._record_channel_forward(msg)
            return

        chat = getattr(update, "effective_chat", None) or getattr(msg, "chat", None)
        user = getattr(update, "effective_user", None) or getattr(msg, "from_user", None)
        chat_type = str(getattr(chat, "type", "")) if chat else ""

        chat_id = (
            str(chat.id)
            if chat and getattr(chat, "id", None) is not None and not hasattr(chat.id, "_mock_name")
            else ""
        )
        user_id = (
            str(user.id)
            if user and getattr(user, "id", None) is not None and not hasattr(user.id, "_mock_name")
            else None
        )

        # Thread the reply into the same topic/thread as the incoming message
        message_thread_id = getattr(msg, "message_thread_id", None)

        # Check authorization (allowed user or allowed channel/chat)
        user_auth = self.is_user_authorized(user_id)
        chat_auth = self.is_chat_authorized(chat_id)

        if not user_auth and not chat_auth:
            logger.warning(
                "Unauthorized Telegram access attempt from user_id: %s, chat_id: %s",
                user_id,
                chat_id,
            )
            chat_type = str(getattr(chat, "type", "")) if chat else ""
            if chat_type != "channel":
                with contextlib.suppress(Exception):
                    await msg.reply_text(
                        "⛔ Access denied. Your user ID or chat is not authorized.",
                        reply_to_message_id=msg.message_id,
                        message_thread_id=message_thread_id,
                        allow_sending_without_reply=True,
                    )
            return

        # 1. React with an emoji (e.g. "👀") to acknowledge and indicate active processing
        try:
            if hasattr(msg, "set_reaction"):
                await msg.set_reaction(reaction="👀")
            elif (
                context
                and getattr(context, "bot", None)
                and hasattr(context.bot, "set_message_reaction")
            ):
                await context.bot.set_message_reaction(
                    chat_id=chat.id if chat else chat_id,
                    message_id=msg.message_id,
                    reaction="👀",
                )
        except Exception as reaction_err:
            # A missing reaction must never block the reply, but it should not fail silently.
            logger.warning(
                "Failed to set 👀 reaction on message %s in chat %s: %s: %s",
                getattr(msg, "message_id", None),
                chat_id,
                type(reaction_err).__name__,
                reaction_err,
            )

        # 2. Trigger typing status in chat
        with contextlib.suppress(Exception):
            if chat and hasattr(chat, "send_action"):
                await chat.send_action(action="typing")
            elif (
                context
                and getattr(context, "bot", None)
                and hasattr(context.bot, "send_chat_action")
            ):
                await context.bot.send_chat_action(
                    chat_id=chat.id if chat else chat_id,
                    action="typing",
                )

        # 3. Create streamer for real-time draft updates
        bot_instance = (
            getattr(context, "bot", None)
            if context and getattr(context, "bot", None)
            else (self._app.bot if self._app else None)
        )
        streamer = TelegramDraftStreamer(bot=bot_instance, chat_id=chat_id)
        streamer_key = (str(chat_id), streamer.draft_id)
        self._active_streamers[streamer_key] = streamer
        try:
            with contextlib.suppress(Exception):
                await streamer.start_thinking()

            text = str(msg.text).strip()

            # 4. Handle /feedback or /teach command
            if text.startswith("/feedback") or text.startswith("/teach"):
                await self._handle_feedback_command(msg, text)
                return

            username = None
            if (
                user
                and getattr(user, "username", None)
                and not hasattr(user.username, "_mock_name")
            ):
                username = str(user.username)
            elif (
                chat
                and getattr(chat, "username", None)
                and not hasattr(chat.username, "_mock_name")
            ):
                username = str(chat.username)

            first_name = "User"
            if (
                user
                and getattr(user, "first_name", None)
                and not hasattr(user.first_name, "_mock_name")
            ):
                first_name = str(user.first_name)
            elif chat and getattr(chat, "title", None) and not hasattr(chat.title, "_mock_name"):
                first_name = str(chat.title)

            reply_to_message_id: str | None = None
            replied = getattr(msg, "reply_to_message", None)
            replied_id = getattr(replied, "message_id", None) if replied is not None else None
            if isinstance(replied_id, int) and not isinstance(replied_id, bool):
                reply_to_message_id = str(replied_id)

            incoming = IncomingMessage(
                message_id=str(msg.message_id),
                chat_id=chat_id,
                user=ChatUser(
                    user_id=user_id or chat_id,
                    username=username,
                    first_name=first_name,
                ),
                text=text,
                reply_to_message_id=reply_to_message_id,
                message_thread_id=str(message_thread_id) if message_thread_id is not None else None,
            )

            for handler in self._message_handlers:
                try:
                    accepts_on_token = False
                    try:
                        sig = inspect.signature(handler)
                        accepts_on_token = "on_token" in sig.parameters or any(
                            p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
                        )
                    except (ValueError, TypeError):
                        pass

                    if accepts_on_token:
                        reply = await handler(incoming, on_token=streamer.on_token)
                    else:
                        reply = await handler(incoming)

                    if reply and not streamer.is_stopped():
                        await self._reply_to_chat(msg, reply, chat_id, chat_type, message_thread_id)
                except (asyncio.CancelledError, GeneratorExit):
                    logger.info(
                        "Message generation cancelled by user for draft %s in chat %s",
                        streamer.draft_id,
                        chat_id,
                    )
                    return
                except Exception as exc:
                    logger.error("Error executing message handler: %s", exc)
                    with contextlib.suppress(Exception):
                        await msg.reply_text(
                            f"⚠️ Error processing request: {exc}",
                            reply_to_message_id=msg.message_id,
                            message_thread_id=message_thread_id,
                            allow_sending_without_reply=True,
                        )
        finally:
            self._active_streamers.pop(streamer_key, None)
