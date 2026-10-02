"""Entry point of operator messages into the LYOKO graph."""

import logging
import uuid
from collections.abc import Callable
from typing import Any

from lyoko.application.chat_sessions import (
    DEFAULT_SESSION_IDLE_TIMEOUT_SECONDS,
    ChatSessionTracker,
)
from lyoko.application.workflow import EVENT_MESSAGE
from lyoko.domain.interfaces.tracer import TracerInterface
from lyoko.domain.models.chat import IncomingMessage

logger = logging.getLogger("lyoko.chat_agent")

NEW_SESSION_COMMAND = "/new"
TRACE_NAME = "telegram-chat-interaction"


def is_new_session_command(text: str) -> bool:
    """Return True for ``/new`` (optionally addressed as ``/new@botname``)."""
    first_token = text.strip().split(maxsplit=1)[0].lower() if text.strip() else ""
    return first_token == NEW_SESSION_COMMAND or first_token.startswith(f"{NEW_SESSION_COMMAND}@")


class InteractiveChatAgent:
    """Turns each chat message into one run of the LYOKO graph and returns the reply.

    The graph decides what the message is (a conversation or an incident to work through) and
    answers it. This class only handles what is specific to chat: sessions, the ``/new``
    command, and the trace each message starts.

    ``graph_provider`` returns the compiled graph. It is a callable because the composition root
    replaces the graph at startup, once the database checkpointer is available.
    """

    def __init__(
        self,
        graph_provider: Callable[[], Any],
        tracer: TracerInterface | None = None,
        session_idle_timeout_seconds: float = DEFAULT_SESSION_IDLE_TIMEOUT_SECONDS,
        session_tracker: ChatSessionTracker | None = None,
    ) -> None:
        self._graph_provider = graph_provider
        self.tracer = tracer
        self.session_tracker = session_tracker or ChatSessionTracker(session_idle_timeout_seconds)

    async def handle_message(self, message: IncomingMessage) -> str:
        """Process an incoming chat message and return the reply for the operator."""
        logger.info("Processing chat message from user %s: %s", message.user.user_id, message.text)
        if is_new_session_command(message.text):
            session_id = self.session_tracker.start_new(message.chat_id)
            logger.info("Started new session %s for chat %s", session_id, message.chat_id)
            return "🆕 Started a new session. Previous context will not be grouped with this one."

        session_id = self.session_tracker.get_session_id(
            message.chat_id, reply_to_message_id=message.reply_to_message_id
        )
        # Short on purpose: the id prefixes approval ids, which Telegram limits to 64 bytes.
        event_id = f"chat-{uuid.uuid4().hex[:8]}"

        state = {
            "event_type": EVENT_MESSAGE,
            "event_id": event_id,
            "session_id": session_id,
            "chat_id": message.chat_id,
            "text": message.text,
            "labels": {},
            "annotations": {},
        }
        config = self._trace_config(message, session_id)
        config.setdefault("configurable", {})["thread_id"] = event_id

        try:
            result = await self._graph_provider().ainvoke(state, config=config)
        except Exception as exc:
            logger.error("Failed to process chat message: %s", exc, exc_info=True)
            return f"⚠️ Error processing your question: {exc}"
        return str(result.get("reply") or "")

    def _trace_config(self, message: IncomingMessage, session_id: str) -> dict[str, Any]:
        tags = ["telegram", "interactive-chat", f"chat:{message.chat_id}"]
        metadata = {
            "chat_id": message.chat_id,
            "username": message.user.username,
            "message_id": message.message_id,
        }
        if self.tracer is not None:
            return self.tracer.get_trace_config(
                session_id=session_id,
                user_id=str(message.user.user_id),
                trace_name=TRACE_NAME,
                tags=tags,
                metadata=metadata,
            )
        return {"run_name": TRACE_NAME, "tags": tags, "metadata": metadata}
