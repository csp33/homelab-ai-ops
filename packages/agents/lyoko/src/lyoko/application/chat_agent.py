"""Interactive conversational agent for LYOKO."""

import logging
from typing import Any

from lyoko.domain.interfaces.llm import LLMClientInterface
from lyoko.domain.models.chat import IncomingMessage

logger = logging.getLogger("lyoko.chat_agent")

SYSTEM_PROMPT = """You are LYOKO, the Homelab AIOps assistant.
You help the administrator inspect Kubernetes clusters, Home Assistant smart devices, and UniFi network appliances.
Be concise, clear, and format all technical responses in clean Markdown."""


class InteractiveChatAgent:
    """Conversational assistant handling interactive user queries via chat connectors."""

    def __init__(self, mcp_client: Any, llm: LLMClientInterface | None = None) -> None:
        self.mcp_client = mcp_client
        self.llm = llm

    async def handle_message(self, message: IncomingMessage) -> str:
        """Process incoming chat query and return conversational response."""
        logger.info("Processing chat message from user %s: %s", message.user.user_id, message.text)
        if self.llm is None:
            return f"Received message: '{message.text}'. (LLM provider not configured)"

        try:
            return await self.llm.chat(
                prompt=message.text,
                system_prompt=SYSTEM_PROMPT,
            )
        except Exception as exc:
            logger.error("Failed to generate LLM response: %s", exc)
            return f"⚠️ Error processing your question: {exc}"
