"""Short-term conversation history for chat threads.

Provides in-memory, per-chat-and-per-thread context so follow-up messages in the same
thread are answered with the previous exchanges in view.
"""

from collections import deque

MAX_CONVERSATION_HISTORY = 10


class ChatHistoryTracker:
    """Track recent conversation turns for short-term chat context.

    History is scoped per chat and per thread/topic, so replies inside one thread do not
    pollute another thread's context, while plain messages in the same chat still share
    their history.
    """

    def __init__(self, max_turns: int = MAX_CONVERSATION_HISTORY):
        self.max_turns = max_turns
        self._histories: dict[tuple[str, str | None], deque[str]] = {}

    def _key(self, chat_id: str, thread_id: str | None) -> tuple[str, str | None]:
        return (chat_id, thread_id)

    def get_history_context(self, chat_id: str, thread_id: str | None = None) -> str:
        """Return previous conversation turns as context for the LLM prompt."""
        turns = self._histories.get(self._key(chat_id, thread_id))
        if not turns:
            return ""
        history_lines = [f"Turn:\n{turn}" for turn in turns]
        return (
            "\n\n--- PREVIOUS CONVERSATION IN THIS CHAT (for context) ---\n"
            + "\n\n".join(history_lines)
            + "\n------------------------------------------------------\n"
        )

    def record_turn(
        self,
        chat_id: str,
        user_text: str,
        assistant_reply: str,
        thread_id: str | None = None,
    ) -> None:
        """Append one user/assistant exchange to the conversation history."""
        turn = f"Operator: {user_text}\nLYOKO: {assistant_reply}"
        key = self._key(chat_id, thread_id)
        if key not in self._histories:
            self._histories[key] = deque(maxlen=self.max_turns)
        self._histories[key].append(turn)

    def clear(self, chat_id: str, thread_id: str | None = None) -> None:
        """Drop the stored conversation for a chat/thread (used by ``/new``)."""
        self._histories.pop(self._key(chat_id, thread_id), None)
