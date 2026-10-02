"""Interactive conversational agent for LYOKO."""

import logging
from typing import Any

from lyoko.domain.interfaces.llm import LLMClientInterface
from lyoko.domain.models.chat import IncomingMessage

logger = logging.getLogger("lyoko.chat_agent")

SYSTEM_PROMPT = """You are LYOKO, the autonomous Homelab AIOps assistant.
You help the administrator inspect and manage:
- Kubernetes clusters and pods (diagnostics, logs, resource limits)
- Home Assistant smart home infrastructure (devices, entities, floors, areas)
- UniFi network appliances (clients, APs, switches, ports)
- Grafana observability metrics and alerts

When answering questions about the current state of devices, networks, or infrastructure, ALWAYS use the available tools (gateway_list_tools to find relevant capabilities, and gateway_call_tool to execute them) before answering.
Be concise, accurate, and format your responses in clean Markdown."""


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
