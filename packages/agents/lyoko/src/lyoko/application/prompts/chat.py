"""System prompt provider for the conversational branch."""

from lyoko.application.context.loader import build_agent_context
from lyoko.application.prompts.loader import load_prompt


class ChatPromptProvider:
    """Provides system prompts for the conversational chat branch."""

    @staticmethod
    def get_prompt() -> str:
        return f"{load_prompt('chat.md')}\n\n{build_agent_context('chat')}"


CHAT_SYSTEM_PROMPT = ChatPromptProvider.get_prompt()
