"""System prompt of the conversational branch."""

from lyoko.application.prompts.loader import load_prompt

CHAT_SYSTEM_PROMPT = load_prompt("chat.md")
