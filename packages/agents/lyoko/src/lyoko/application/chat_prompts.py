"""System prompt of the conversational branch."""

from lyoko.application.context.loader import build_agent_context
from lyoko.application.prompts.loader import load_prompt

CHAT_SYSTEM_PROMPT = f"{load_prompt('chat.md')}\n\n{build_agent_context('chat')}"
