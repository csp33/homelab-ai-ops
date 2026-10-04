"""Streaming Telegram replies via an editable progress-log message.

Telegram's native ``sendMessageDraft`` only targets private chats and shows an ephemeral
30-second preview that refused to stay alive here. Instead this sends a real message and edits it
in place: it grows a checklist of the steps actually running (the specialist and tools the agent
calls), then replaces the whole message with the final formatted answer. Works in private chats,
groups, channels, and channel discussion threads.
"""

import asyncio
import contextlib
import logging
import re
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

logger = logging.getLogger("lyoko.chat.telegram")

INITIAL_STATUS = "Thinking…"
STOP_CALLBACK_PREFIX = "stop"
MAX_MESSAGE_LENGTH = 4096
_TAG_PATTERN = re.compile(r"<[^>]+>")


class TelegramStreamingReply:
    """An editable message that shows a live checklist of the steps the agent runs."""

    def __init__(
        self,
        bot: Any,
        chat_id: str | int,
        reply_to_message_id: str | int | None = None,
        message_thread_id: str | int | None = None,
        status_interval_seconds: float = 2.5,
        finalize_delay_seconds: float = 3.5,
        parse_mode: str = "HTML",
    ) -> None:
        self.bot = bot
        self.chat_id = chat_id
        self.reply_to_message_id = reply_to_message_id
        self.message_thread_id = message_thread_id
        self.status_interval_seconds = status_interval_seconds
        self.finalize_delay_seconds = finalize_delay_seconds
        self.parse_mode = parse_mode
        self.message_id: int | None = None
        self.draft_id = abs(hash(f"{chat_id}_{id(self)}")) % 2147483640 + 1
        self._steps: list[str] = [INITIAL_STATUS]
        self._lock = asyncio.Lock()
        self._disabled = False
        self._stopped = asyncio.Event()
        self._status_task: asyncio.Task[None] | None = None
        self._started_at = 0.0

    def stop(self) -> None:
        """Signal that message generation should stop immediately."""
        self._stopped.set()

    def is_stopped(self) -> bool:
        """Return True if message generation was stopped."""
        return self._stopped.is_set()

    def _int_or_none(self, value: str | int | None) -> int | None:
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _stop_markup(self) -> InlineKeyboardMarkup:
        button = InlineKeyboardButton(
            text="⏹ Stop", callback_data=f"{STOP_CALLBACK_PREFIX}:{self.draft_id}"
        )
        return InlineKeyboardMarkup([[button]])

    def _render(self, done: bool = False) -> str:
        """Render the checklist: completed steps get a check, the active one a timer."""
        lines = ["<b>🧠 Progress</b>"]
        last = len(self._steps) - 1
        elapsed = int(asyncio.get_event_loop().time() - self._started_at)
        for index, step in enumerate(self._steps):
            if index < last or done:
                lines.append(f"✔ {step}")
            else:
                lines.append(f"⏳ {step} · {elapsed}s")
        return "\n".join(lines)

    async def start(self) -> None:
        """Send the placeholder message, threaded to the originating message."""
        if not self.bot or not hasattr(self.bot, "send_message"):
            self._disabled = True
            return
        self._started_at = asyncio.get_event_loop().time()
        kwargs: dict[str, Any] = {"chat_id": self.chat_id, "text": self._render()}
        reply_to = self._int_or_none(self.reply_to_message_id)
        thread = self._int_or_none(self.message_thread_id)
        if reply_to is not None:
            kwargs["reply_to_message_id"] = reply_to
            kwargs["allow_sending_without_reply"] = True
        if thread is not None:
            kwargs["message_thread_id"] = thread
        try:
            sent = await self.bot.send_message(
                parse_mode=self.parse_mode, reply_markup=self._stop_markup(), **kwargs
            )
            self.message_id = getattr(sent, "message_id", None)
            self._status_task = asyncio.create_task(self._status_loop())
        except Exception as exc:
            logger.warning(
                "Telegram streaming placeholder failed for chat %s: %s", self.chat_id, exc
            )
            self._disabled = True

    async def _status_loop(self) -> None:
        """Refresh the active step's elapsed timer until finalization."""
        try:
            while not self._stopped.is_set() and not self._disabled:
                await asyncio.sleep(self.status_interval_seconds)
                if self._stopped.is_set() or self._disabled or self.message_id is None:
                    return
                async with self._lock:
                    if self._stopped.is_set() or self._disabled:
                        return
                    await self._edit(self._render(), parse_mode=self.parse_mode)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.debug("Telegram status refresh stopped for chat %s: %s", self.chat_id, exc)

    async def _cancel_status(self) -> None:
        """Stop the timer refresh before it can race a final edit."""
        task = self._status_task
        self._status_task = None
        if task is None or task.done():
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    async def set_status(self, text: str) -> None:
        """Append a factual step (the specialist or tool actually running) to the checklist."""
        if self._disabled or self.message_id is None or self._stopped.is_set():
            return
        if self._steps[-1] == text:
            return
        self._steps.append(text)
        async with self._lock:
            if self._stopped.is_set() or self._disabled or self.message_id is None:
                return
            await self._edit(self._render(), parse_mode=self.parse_mode)

    async def _edit(
        self, text: str, parse_mode: str | None, reply_markup: Any = "__keep__"
    ) -> bool:
        if self.message_id is None:
            return False
        kwargs: dict[str, Any] = {
            "chat_id": self.chat_id,
            "message_id": self.message_id,
            "text": text[:MAX_MESSAGE_LENGTH],
        }
        if parse_mode:
            kwargs["parse_mode"] = parse_mode
        if reply_markup != "__keep__":
            kwargs["reply_markup"] = reply_markup
        try:
            await self.bot.edit_message_text(**kwargs)
            return True
        except Exception as exc:
            if "not modified" in str(exc).lower():
                return True
            logger.debug("Telegram stream edit failed for chat %s: %s", self.chat_id, exc)
            return False

    async def _edit_html_with_plain_fallback(self, text: str) -> bool:
        if await self._edit(text, parse_mode=self.parse_mode, reply_markup=None):
            return True
        plain = _TAG_PATTERN.sub("", text)
        return await self._edit(plain, parse_mode=None, reply_markup=None)

    def _done_text(self) -> str:
        """Completed checklist plus a Done marker, kept until the answer replaces it."""
        elapsed = int(asyncio.get_event_loop().time() - self._started_at)
        return f"{self._render(done=True)}\n\n✅ <b>Done</b> · {elapsed}s"

    async def finalize(self, formatted_text: str) -> bool:
        """Mark the checklist done, then replace the whole message with the final answer.

        The operator keeps watching the completed tool list with a ``Done`` footer for a few
        seconds, after which the transient steps are swapped out for the answer.
        """
        await self._cancel_status()
        if self._disabled or self.message_id is None:
            return False
        await self._edit_html_with_plain_fallback(self._done_text())
        if self.finalize_delay_seconds > 0:
            await asyncio.sleep(self.finalize_delay_seconds)
        if self._stopped.is_set():
            return False
        return await self._edit_html_with_plain_fallback(formatted_text)

    async def finalize_stopped(self) -> None:
        """Freeze the checklist with a stopped note when the operator pressed stop."""
        await self._cancel_status()
        text = f"{self._render(done=True)}\n\n⏹ <i>Generation stopped</i>"
        if not await self._edit_html_with_plain_fallback(text):
            await self.discard()

    async def discard(self) -> None:
        """Delete the placeholder when no answer will replace it."""
        await self._cancel_status()
        if self._disabled or self.message_id is None or not self.bot:
            return
        try:
            await self.bot.delete_message(chat_id=self.chat_id, message_id=self.message_id)
        except Exception as exc:
            logger.debug("Could not delete streaming placeholder in chat %s: %s", self.chat_id, exc)
