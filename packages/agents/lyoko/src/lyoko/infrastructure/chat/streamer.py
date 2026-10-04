"""Streaming draft updates for Telegram messages.

Wraps Telegram's native ``sendMessageDraft`` API with rate-limiting and stop support so a long
LLM response can be shown as it is generated.
"""

import asyncio
import logging
from typing import Any

logger = logging.getLogger("lyoko.chat.telegram")


class TelegramDraftStreamer:
    """Streams draft messages to Telegram using the native sendMessageDraft API with rate-limiting and stop support."""

    def __init__(
        self,
        bot: Any,
        chat_id: int | str,
        chat_type: str = "",
        draft_id: int | None = None,
        min_interval_seconds: float = 0.4,
    ) -> None:
        self.bot = bot
        self.chat_id = chat_id
        self.chat_type = chat_type
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
        self._can_stop = True
        self._stopped = asyncio.Event()

    def stop(self) -> None:
        """Signal that message generation should stop immediately."""
        self._stopped.set()
        self._disabled = True

    def is_stopped(self) -> bool:
        """Return True if message generation was stopped."""
        return self._stopped.is_set()

    async def _send_draft(self, text: str) -> None:
        """Send or update the draft, retrying without ``can_stop`` if the server rejects it.

        ``can_stop`` is a Bot API 10.0 addition. Older servers reject the call outright, which
        would otherwise disable streaming even where it is supported, so fall back to a plain
        draft update the first time it fails and remember that ``can_stop`` is unavailable.
        """
        target_chat_id = int(self.chat_id)
        base_kwargs: dict[str, Any] = {
            "chat_id": target_chat_id,
            "draft_id": self.draft_id,
            "text": text,
        }
        if self._can_stop:
            try:
                await self.bot.send_message_draft(**base_kwargs, api_kwargs={"can_stop": True})
                return
            except Exception as exc:
                logger.debug(
                    "send_message_draft with can_stop failed, retrying without it: %s", exc
                )
                self._can_stop = False
        await self.bot.send_message_draft(**base_kwargs)

    async def start_thinking(self) -> None:
        """Send initial empty draft to show native 'Thinking...' placeholder with Stop button."""
        # send_message_draft only works in private chats (per Telegram API)
        if self.chat_type != "private":
            self._disabled = True
            return
        if not self.bot or not hasattr(self.bot, "send_message_draft"):
            self._disabled = True
            return
        try:
            await self._send_draft("")
        except Exception as exc:
            logger.debug(
                "send_message_draft start_thinking not supported or failed for chat %s: %s",
                self.chat_id,
                exc,
            )
            self._disabled = True

    async def on_token(self, token: str) -> None:
        """Receive a token, append to buffer, and update draft if throttle interval elapsed."""
        if self._stopped.is_set():
            raise asyncio.CancelledError("Message generation stopped by user via Telegram")
        if self.chat_type != "private" or self._disabled or not self.bot:
            return
        if not hasattr(self.bot, "send_message_draft"):
            return
        self._accumulated_text += token
        now = asyncio.get_event_loop().time()
        if (now - self._last_sent_time) >= self.min_interval_seconds:
            await self._flush_locked(now)

    async def _flush_locked(self, now: float) -> None:
        if self._accumulated_text == self._last_sent_text:
            return
        async with self._lock:
            if self._disabled or self._stopped.is_set():
                return
            try:
                self._last_sent_time = now
                self._last_sent_text = self._accumulated_text
                await self._send_draft(self._accumulated_text)
            except Exception as exc:
                logger.debug("send_message_draft error: %s", exc)
                self._disabled = True
