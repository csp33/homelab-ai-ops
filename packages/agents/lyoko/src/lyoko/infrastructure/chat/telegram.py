"""Telegram chat connector adapter implementation using python-telegram-bot."""

import asyncio
import contextlib
import html
import inspect
import logging
import re
from collections.abc import Awaitable, Callable
from typing import Any

from lyoko.domain.interfaces.chat_connector import ChatConnector
from lyoko.domain.models.chat import (
    ApprovalRequest,
    ApprovalResponse,
    ChatUser,
    IncomingMessage,
    SentMessage,
)
from lyoko.domain.models.memory import MemoryEntry
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


class TelegramDraftStreamer:
    """Streams draft messages to Telegram using the native sendMessageDraft API with rate-limiting."""

    def __init__(
        self,
        bot: Any,
        chat_id: int | str,
        draft_id: int | None = None,
        min_interval_seconds: float = 0.4,
    ) -> None:
        self.bot = bot
        self.chat_id = chat_id
        self.draft_id = (
            draft_id
            if draft_id is not None
            else (abs(hash(f"{chat_id}_{id(self)}")) % 2147483640 + 1)
        )
        self.min_interval_seconds = min_interval_seconds
        self._accumulated_text = ""
        self._last_sent_time = 0.0
        self._last_sent_text = ""
        self._lock = asyncio.Lock()
        self._disabled = False

    async def start_thinking(self) -> None:
        """Send initial empty draft to show native 'Thinking...' placeholder."""
        if not self.bot or not hasattr(self.bot, "send_message_draft"):
            return
        try:
            target_chat_id = int(self.chat_id)
            await self.bot.send_message_draft(
                chat_id=target_chat_id,
                draft_id=self.draft_id,
                text="",
            )
        except Exception as exc:
            logger.debug(
                "send_message_draft start_thinking not supported or failed for chat %s: %s",
                self.chat_id,
                exc,
            )
            self._disabled = True

    async def on_token(self, token: str) -> None:
        """Receive a token, append to buffer, and update draft if throttle interval elapsed."""
        if self._disabled or not self.bot or not hasattr(self.bot, "send_message_draft"):
            return
        self._accumulated_text += token
        now = asyncio.get_event_loop().time()
        if (now - self._last_sent_time) >= self.min_interval_seconds:
            await self._flush_locked(now)

    async def _flush_locked(self, now: float) -> None:
        if self._accumulated_text == self._last_sent_text:
            return
        async with self._lock:
            if self._disabled:
                return
            try:
                target_chat_id = int(self.chat_id)
                self._last_sent_time = now
                self._last_sent_text = self._accumulated_text
                await self.bot.send_message_draft(
                    chat_id=target_chat_id,
                    draft_id=self.draft_id,
                    text=self._accumulated_text,
                )
            except Exception as exc:
                logger.debug("send_message_draft error: %s", exc)
                self._disabled = True


def _to_sent_message(result: object, fallback_chat_id: str) -> SentMessage | None:
    """Convert a python-telegram-bot ``Message`` into a domain ``SentMessage`` reference."""
    message_id = getattr(result, "message_id", None)
    if not isinstance(message_id, int) or isinstance(message_id, bool):
        return None
    chat_id = getattr(result, "chat_id", None)
    if not isinstance(chat_id, (int, str)) or isinstance(chat_id, bool):
        chat_id = fallback_chat_id
    return SentMessage(chat_id=str(chat_id), message_id=str(message_id))


# Telegram has no table support. Tables narrower than this many characters are rendered as
# aligned monospace blocks; wider ones wrap badly on phones, so they become per-row cards.
MAX_TABLE_PRE_WIDTH = 42

_TABLE_SEPARATOR_RE = re.compile(r"^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$")
_EMPTY_CELL_VALUES = {"", "-", "—", "–"}


def _split_table_row(line: str) -> list[str]:
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [_clean_table_cell(cell) for cell in stripped.split("|")]


def _clean_table_cell(cell: str) -> str:
    """Strip inline Markdown from a table cell so it renders as plain text."""
    cell = re.sub(r"<br\s*/?>", " ", cell, flags=re.IGNORECASE)
    cell = re.sub(r"\[(.+?)\]\((https?://[^\s)]+)\)", r"\1", cell)
    cell = cell.replace("**", "").replace("`", "")
    return cell.strip()


def _is_table_start(lines: list[str], index: int) -> bool:
    if index + 1 >= len(lines):
        return False
    header, separator = lines[index], lines[index + 1]
    return "|" in header and "|" in separator and bool(_TABLE_SEPARATOR_RE.match(separator))


def _render_table(rows: list[list[str]]) -> tuple[str, bool]:
    """Render parsed table rows. Returns (text, is_preformatted)."""
    header, body = rows[0], rows[1:]
    columns = len(header)
    body = [(row + [""] * columns)[:columns] for row in body]

    widths = [max(len(r[i]) for r in [header, *body]) for i in range(columns)]
    total_width = sum(widths) + 2 * (columns - 1)

    if total_width <= MAX_TABLE_PRE_WIDTH:
        lines = ["  ".join(cell.ljust(widths[i]) for i, cell in enumerate(header)).rstrip()]
        lines.append("  ".join("─" * w for w in widths))
        lines.extend(
            "  ".join(c.ljust(widths[i]) for i, c in enumerate(row)).rstrip() for row in body
        )
        return "\n".join(lines), True

    cards: list[str] = []
    for row in body:
        card = [f"**{row[0] or header[0]}**"]
        card.extend(
            f"• {header[i]}: {row[i]}"
            for i in range(1, columns)
            if row[i] not in _EMPTY_CELL_VALUES
        )
        cards.append("\n".join(card))
    return "\n\n".join(cards), False


def _convert_markdown_tables(text: str, code_blocks: list[str]) -> str:
    """Replace Markdown tables with Telegram-friendly text (Telegram cannot render tables)."""
    lines = text.split("\n")
    output: list[str] = []
    i = 0
    while i < len(lines):
        if not _is_table_start(lines, i):
            output.append(lines[i])
            i += 1
            continue

        rows = [_split_table_row(lines[i])]
        i += 2  # skip header + separator
        while i < len(lines) and "|" in lines[i] and lines[i].strip():
            rows.append(_split_table_row(lines[i]))
            i += 1

        rendered, preformatted = _render_table(rows)
        if preformatted:
            code_blocks.append(rendered)
            output.append(f"@@CODE_BLOCK_{len(code_blocks) - 1}@@")
        else:
            output.append(rendered)
    return "\n".join(output)


def markdown_to_telegram_html(text: str) -> str:
    """Convert standard Markdown output from LLMs to Telegram-compatible HTML formatting."""
    if not text:
        return ""

    # 1. Extract and preserve code blocks
    code_blocks: list[str] = []

    def save_code_block(match: re.Match) -> str:
        code_blocks.append(match.group(2))
        return f"@@CODE_BLOCK_{len(code_blocks) - 1}@@"

    # Match ```lang\ncode``` or ```code```
    processed = re.sub(r"```([a-zA-Z0-9_-]*\n)?(.*?)```", save_code_block, text, flags=re.DOTALL)

    # 1b. Convert Markdown tables (unsupported by Telegram) into monospace blocks or cards
    processed = _convert_markdown_tables(processed, code_blocks)

    # 2. Extract and preserve inline code
    inline_codes: list[str] = []

    def save_inline_code(match: re.Match) -> str:
        inline_codes.append(match.group(1))
        return f"@@INLINE_CODE_{len(inline_codes) - 1}@@"

    processed = re.sub(r"`([^`\n]+)`", save_inline_code, processed)

    # 3. HTML escape standard text so '<', '>', '&' don't break Telegram parser
    processed = html.escape(processed)

    # 4. Headers (# Title -> <b>Title</b>)
    processed = re.sub(r"^#{1,6}\s*(.+)$", r"<b>\1</b>", processed, flags=re.MULTILINE)

    # 5. Bold (**bold**)
    processed = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", processed)

    # 6. Italic (*italic* only when surrounded by non-alphanumeric or word boundaries)
    processed = re.sub(r"(?<!\w)\*([^*]+?)\*(?!\w)", r"<i>\1</i>", processed)

    # 7. Links [title](url)
    processed = re.sub(r"\[(.+?)\]\((https?://[^\s)]+)\)", r'<a href="\2">\1</a>', processed)

    # 8. Restore inline code (HTML escaped content inside <code>)
    for i, code in enumerate(inline_codes):
        processed = processed.replace(f"@@INLINE_CODE_{i}@@", f"<code>{html.escape(code)}</code>")

    # 9. Restore code blocks (HTML escaped content inside <pre>)
    for i, code in enumerate(code_blocks):
        processed = processed.replace(
            f"@@CODE_BLOCK_{i}@@", f"<pre><code>{html.escape(code.strip())}</code></pre>"
        )

    return processed


class TelegramConnector(ChatConnector):
    """Telegram adapter implementing ChatConnector port using python-telegram-bot.

    Supports private 1-on-1 chats, group chats, and Telegram channels for
    interactive assistant communication, alert broadcasting, HITL approvals, and memory feedback.
    """

    def __init__(
        self,
        bot_token: str | SecretStr | None,
        allowed_user_ids: set[str] | list[str] | str | None = None,
        allowed_chat_ids: set[str] | list[str] | str | None = None,
        default_chat_id: str | None = None,
        memory_repository: Any = None,
        embeddings_service: Any = None,
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

        self.memory_repository = memory_repository
        self.embeddings_service = embeddings_service

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
                        "⛔ Access denied. Your user ID or chat is not authorized.",
                        reply_to_message_id=msg.message_id,
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
        with contextlib.suppress(Exception):
            await streamer.start_thinking()

        text = str(msg.text).strip()

        # 4. Handle /feedback or /teach command
        if text.startswith("/feedback") or text.startswith("/teach"):
            await self._handle_feedback_command(msg, text)
            return

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
                if reply:
                    formatted_reply = markdown_to_telegram_html(reply)
                    try:
                        await msg.reply_text(
                            formatted_reply,
                            parse_mode="HTML",
                            reply_to_message_id=msg.message_id,
                            allow_sending_without_reply=True,
                        )
                    except Exception as html_err:
                        logger.warning("Failed to reply with HTML, falling back: %s", html_err)
                        try:
                            await msg.reply_text(
                                reply,
                                reply_to_message_id=msg.message_id,
                                allow_sending_without_reply=True,
                            )
                        except Exception:
                            await self.send_message(
                                chat_id=chat_id,
                                text=reply,
                                reply_to_message_id=msg.message_id,
                            )
            except Exception as exc:
                logger.error("Error executing message handler: %s", exc)
                with contextlib.suppress(Exception):
                    await msg.reply_text(
                        f"⚠️ Error processing request: {exc}",
                        reply_to_message_id=msg.message_id,
                        allow_sending_without_reply=True,
                    )

    async def _handle_feedback_command(self, msg: Any, text: str) -> None:
        """Process /feedback or /teach operator instruction and persist to PostgreSQL."""
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
                allow_sending_without_reply=True,
            )
            return

        if not self.memory_repository:
            await msg.reply_text(
                "⚠️ The persistent memory database (PostgreSQL) is not available.",
                reply_to_message_id=msg.message_id,
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
            allow_sending_without_reply=True,
        )

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
        is_feedback = action_type.lower() in ["feedback", "teach", "redirect"]

        reason = (
            "User confirmed via Telegram button"
            if approved
            else (
                "User requested redirection / teaching new rule"
                if is_feedback
                else "User rejected via Telegram button"
            )
        )

        response = ApprovalResponse(
            incident_id=incident_id,
            approved=approved,
            user_id=user_id,
            action_id=action_type,
            reason=reason,
        )

        for handler in self._approval_handlers:
            try:
                res = handler(response)
                if inspect.isawaitable(res):
                    await res
            except Exception as exc:
                logger.error("Error executing approval handler: %s", exc)

        user_name = html.escape(update.effective_user.first_name or user_id)
        if approved:
            status_text = f"✅ <b>Approved</b> by admin ({user_name})."
        elif is_feedback:
            status_text = (
                f"💡 <b>Redirection / Teaching mode activated</b> by {user_name}.\n\n"
                f"👉 <i>Reply to this message or type:</i>\n"
                f"<code>/feedback &lt;your correction or rule for this service&gt;</code>"
            )
        else:
            status_text = f"❌ <b>Rejected</b> by admin ({user_name})."

        current_text = (
            query.message.text
            if query.message and hasattr(query.message, "text") and query.message.text
            else ""
        )
        if current_text:
            new_text = f"{current_text}\n\n<b>Result:</b> {status_text}"
        else:
            new_text = f"<b>Result:</b> {status_text}"
        try:
            await query.edit_message_text(new_text, parse_mode="HTML")
        except Exception as edit_err:
            logger.debug("Could not edit message text after callback: %s", edit_err)

    async def start(self) -> None:
        """Initialize and start Telegram application and polling loop."""
        if not self.bot_token:
            logger.warning("TelegramConnector not started: missing bot token")
            return

        # Updates are processed one at a time by default. A message handler that waits for an
        # approval would then block the very button click that grants it, so handle them
        # concurrently.
        self._app = Application.builder().token(self.bot_token).concurrent_updates(True).build()
        self._app.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_telegram_message)
        )
        self._app.add_handler(CommandHandler("start", self._handle_telegram_message))
        self._app.add_handler(CommandHandler("help", self._handle_telegram_message))
        self._app.add_handler(CommandHandler("new", self._handle_telegram_message))
        self._app.add_handler(CommandHandler("feedback", self._handle_telegram_message))
        self._app.add_handler(CommandHandler("teach", self._handle_telegram_message))
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

    async def send_message(
        self,
        chat_id: str,
        text: str,
        reply_to_message_id: str | int | None = None,
        parse_mode: str = "HTML",
    ) -> SentMessage | None:
        """Send proactive text message to specific chat, group, or channel."""
        if not self._app or not self._app.bot:
            return None
        target = chat_id or self.default_chat_id
        if not target:
            return None

        msg_id = int(reply_to_message_id) if reply_to_message_id is not None else None

        if parse_mode == "HTML":
            formatted = markdown_to_telegram_html(text)
            try:
                sent = await self._app.bot.send_message(
                    chat_id=target,
                    text=formatted,
                    parse_mode="HTML",
                    reply_to_message_id=msg_id,
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
                allow_sending_without_reply=True,
            )
        except Exception:
            sent = await self._app.bot.send_message(
                chat_id=target,
                text=text,
                reply_to_message_id=msg_id,
                allow_sending_without_reply=True,
            )
        return _to_sent_message(sent, str(target))

    async def send_approval_request(self, request: ApprovalRequest) -> SentMessage | None:
        """Send interactive approval prompt with inline action buttons to chat or channel."""
        if not self._app or not self._app.bot:
            return None
        target = request.chat_id or self.default_chat_id
        if not target:
            return None

        buttons = []
        for act in request.actions:
            cb_data = f"{act.action_id}:{request.incident_id}"
            buttons.append(InlineKeyboardButton(text=act.label, callback_data=cb_data))

        keyboard = InlineKeyboardMarkup([buttons]) if buttons else None
        text = f"🚨 <b>[APPROVAL REQUIRED]</b>\n\n<b>{html.escape(request.title)}</b>\n\n{markdown_to_telegram_html(request.details)}"
        try:
            sent = await self._app.bot.send_message(
                chat_id=target, text=text, reply_markup=keyboard, parse_mode="HTML"
            )
        except Exception as exc:
            logger.warning("Failed to send approval request in HTML, falling back: %s", exc)
            plain_text = f"🚨 [APPROVAL REQUIRED]\n\n{request.title}\n\n{request.details}"
            sent = await self._app.bot.send_message(
                chat_id=target, text=plain_text, reply_markup=keyboard
            )
        return _to_sent_message(sent, str(target))
