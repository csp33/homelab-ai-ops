import contextlib
import logging
from collections.abc import Awaitable, Callable

from lyoko.domain.interfaces.chat_connector import ChatConnector
from lyoko.domain.models.chat import (
    ApprovalRequest,
    ApprovalResponse,
    ChatUser,
    IncomingMessage,
)
from pydantic import SecretStr
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

logger = logging.getLogger("lyoko.chat.telegram")


class TelegramConnector(ChatConnector):
    """Telegram adapter implementing ChatConnector port using python-telegram-bot.

    Supports private 1-on-1 chats, group chats, and Telegram channels for
    interactive assistant communication, alert broadcasting, and HITL approvals.
    """

    def __init__(
        self,
        bot_token: str | SecretStr | None,
        allowed_user_ids: set[str] | list[str] | str | None = None,
        allowed_chat_ids: set[str] | list[str] | str | None = None,
        default_chat_id: str | None = None,
    ) -> None:
        if isinstance(bot_token, SecretStr):
            self.bot_token = bot_token.get_secret_value()
        elif bot_token:
            self.bot_token = str(bot_token)
        else:
            self.bot_token = ""

        if isinstance(allowed_user_ids, str):
            self.allowed_user_ids = {
                uid.strip() for uid in allowed_user_ids.split(",") if uid.strip()
            }
        elif allowed_user_ids:
            self.allowed_user_ids = {
                str(uid).strip() for uid in allowed_user_ids if str(uid).strip()
            }
        else:
            self.allowed_user_ids = set()

        if isinstance(allowed_chat_ids, str):
            self.allowed_chat_ids = {
                cid.strip() for cid in allowed_chat_ids.split(",") if cid.strip()
            }
        elif allowed_chat_ids:
            self.allowed_chat_ids = {
                str(cid).strip() for cid in allowed_chat_ids if str(cid).strip()
            }
        else:
            self.allowed_chat_ids = set()

        self.default_chat_id = str(default_chat_id).strip() if default_chat_id else None
        if self.default_chat_id:
            self.allowed_chat_ids.add(self.default_chat_id)

        self._message_handlers: list[Callable[[IncomingMessage], Awaitable[str | None]]] = []
        self._approval_handlers: list[Callable[[ApprovalResponse], Awaitable[None]]] = []
        self._app: Application | None = None

    def is_user_authorized(self, user_id: str | int | None) -> bool:
        """Verify whether user_id is explicitly allowed by whitelist."""
        if not self.allowed_user_ids or user_id is None:
            return False
        return str(user_id).strip() in self.allowed_user_ids

    def is_chat_authorized(self, chat_id: str | int | None) -> bool:
        """Verify whether chat_id (e.g. channel or group) is explicitly allowed."""
        if not self.allowed_chat_ids or chat_id is None:
            return False
        return str(chat_id).strip() in self.allowed_chat_ids

    def register_message_handler(
        self, handler: Callable[[IncomingMessage], Awaitable[str | None]]
    ) -> None:
        """Register a callback for incoming messages."""
        self._message_handlers.append(handler)

    def register_approval_handler(
        self, handler: Callable[[ApprovalResponse], Awaitable[None]]
    ) -> None:
        """Register a callback for approval button responses."""
        self._approval_handlers.append(handler)

    async def _handle_telegram_message(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle incoming text messages and channel posts from Telegram."""
        msg = getattr(update, "message", None) or getattr(update, "effective_message", None)
        if not msg or not getattr(msg, "text", None):
            return

        chat = getattr(update, "effective_chat", None) or getattr(msg, "chat", None)
        user = getattr(update, "effective_user", None) or getattr(msg, "from_user", None)

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
                        "⛔ Access denied. Your user ID or chat is not authorized."
                    )
            return

        text = str(msg.text)
        username = None
        if user and getattr(user, "username", None) and not hasattr(user.username, "_mock_name"):
            username = str(user.username)
        elif chat and getattr(chat, "username", None) and not hasattr(chat.username, "_mock_name"):
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

        incoming = IncomingMessage(
            message_id=str(msg.message_id),
            chat_id=chat_id,
            user=ChatUser(
                user_id=user_id or chat_id,
                username=username,
                first_name=first_name,
            ),
            text=text,
        )

        for handler in self._message_handlers:
            try:
                reply = await handler(incoming)
                if reply:
                    try:
                        await msg.reply_text(reply, parse_mode="Markdown")
                    except Exception:
                        await self.send_message(chat_id=chat_id, text=reply)
            except Exception as exc:
                logger.error("Error executing message handler: %s", exc)
                with contextlib.suppress(Exception):
                    await msg.reply_text(f"⚠️ Error processing request: {exc}")

    async def _handle_callback_query(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle callback queries generated by inline keyboard buttons."""
        query = update.callback_query
        if not query or not query.data or not update.effective_user:
            return

        user_id = str(update.effective_user.id)
        chat_id = str(update.effective_chat.id) if update.effective_chat else None

        # Button clicks require user authorization (or authorized channel)
        if not self.is_user_authorized(user_id) and not self.is_chat_authorized(chat_id):
            await query.answer("⛔ Unauthorized", show_alert=True)
            return

        await query.answer()

        # Format: "<action_id>:<incident_id>" e.g. "approve:<incident_id>"
        parts = query.data.split(":", 1)
        action_type = parts[0]
        incident_id = parts[1] if len(parts) > 1 else ""
        approved = action_type.lower() == "approve"

        response = ApprovalResponse(
            incident_id=incident_id,
            approved=approved,
            user_id=user_id,
            action_id=action_type,
            reason=(
                "User confirmed via Telegram button"
                if approved
                else "User rejected via Telegram button"
            ),
        )

        for handler in self._approval_handlers:
            try:
                await handler(response)
            except Exception as exc:
                logger.error("Error executing approval handler: %s", exc)

        status_text = "✅ Approved" if approved else "❌ Rejected"
        current_text = (
            query.message.text
            if query.message and hasattr(query.message, "text") and query.message.text
            else ""
        )
        if current_text:
            new_text = f"{current_text}\n\n*Result:* {status_text} by admin ({update.effective_user.first_name or user_id})."
        else:
            new_text = (
                f"*Result:* {status_text} by admin ({update.effective_user.first_name or user_id})."
            )
        try:
            await query.edit_message_text(new_text)
        except Exception as edit_err:
            logger.debug("Could not edit message text after callback: %s", edit_err)

    async def start(self) -> None:
        """Initialize and start Telegram application and polling loop."""
        if not self.bot_token:
            logger.warning("TelegramConnector not started: missing bot token")
            return

        self._app = Application.builder().token(self.bot_token).build()
        self._app.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_telegram_message)
        )
        self._app.add_handler(CommandHandler("start", self._handle_telegram_message))
        self._app.add_handler(CommandHandler("help", self._handle_telegram_message))
        self._app.add_handler(CommandHandler("status", self._handle_telegram_message))
        self._app.add_handler(MessageHandler(filters.COMMAND, self._handle_telegram_message))
        self._app.add_handler(CallbackQueryHandler(self._handle_callback_query))

        await self._app.initialize()
        await self._app.start()
        if self._app.updater:
            await self._app.updater.start_polling()
        logger.info("TelegramConnector started polling updates.")

    async def stop(self) -> None:
        """Gracefully stop polling and terminate Telegram application."""
        if self._app:
            if self._app.updater and self._app.updater.running:
                await self._app.updater.stop()
            await self._app.stop()
            await self._app.shutdown()
            logger.info("TelegramConnector stopped.")

    async def send_message(self, chat_id: str, text: str, parse_mode: str = "Markdown") -> None:
        """Send proactive text message to specific chat, group, or channel."""
        if not self._app or not self._app.bot:
            return
        target = chat_id or self.default_chat_id
        if target:
            await self._app.bot.send_message(chat_id=target, text=text, parse_mode=parse_mode)

    async def send_approval_request(self, request: ApprovalRequest) -> None:
        """Send interactive approval prompt with inline action buttons to chat or channel."""
        if not self._app or not self._app.bot:
            return
        target = request.chat_id or self.default_chat_id
        if not target:
            return

        buttons = []
        for act in request.actions:
            cb_data = f"{act.action_id}:{request.incident_id}"
            buttons.append(InlineKeyboardButton(text=act.label, callback_data=cb_data))

        keyboard = InlineKeyboardMarkup([buttons]) if buttons else None
        text = f"🚨 *[APPROVAL REQUIRED]*\n\n*{request.title}*\n\n{request.details}"
        await self._app.bot.send_message(
            chat_id=target, text=text, reply_markup=keyboard, parse_mode="Markdown"
        )
