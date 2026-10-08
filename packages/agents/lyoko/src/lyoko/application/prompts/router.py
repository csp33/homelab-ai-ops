"""System prompt provider for the event router."""

from lyoko.application.prompts.loader import load_prompt


class RouterPromptProvider:
    """Provides the router system prompt."""

    @staticmethod
    def get_prompt() -> str:
        return load_prompt("router.md")


ROUTER_SYSTEM_PROMPT = RouterPromptProvider.get_prompt()
