"""Interactive conversational agent for LYOKO."""

import logging
from typing import Any

from lyoko.domain.interfaces.llm import LLMClientInterface
from lyoko.domain.models.chat import IncomingMessage

logger = logging.getLogger("lyoko.chat_agent")

SYSTEM_PROMPT = """You are LYOKO, the autonomous Homelab AIOps assistant.
You help the administrator inspect, manage, and diagnose smart infrastructure, services, and homelab appliances.

When answering questions about the current state of devices, networks, or infrastructure, ALWAYS inspect available tools first (use gateway_list_categories to see connected upstream services, gateway_list_tools to find specific tool names/parameters, and gateway_call_tool to execute them) before providing answers.
Be concise, accurate, and format all technical responses in clean Markdown."""


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

        tools = []
        if self.mcp_client and hasattr(self.mcp_client, "get_langchain_tools"):
            tools = self.mcp_client.get_langchain_tools()

        try:
            return await self.llm.chat(
                prompt=message.text,
                system_prompt=SYSTEM_PROMPT,
                tools=tools if tools else None,
            )
        except Exception as exc:
            logger.error("Failed to generate LLM response: %s", exc)
            return f"⚠️ Error processing your question: {exc}"
