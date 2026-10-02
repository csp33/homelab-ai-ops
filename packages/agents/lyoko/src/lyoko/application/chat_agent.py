"""Interactive conversational agent for LYOKO."""

import logging
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from lyoko.config import settings
from lyoko.domain.models.chat import IncomingMessage
from lyoko.infrastructure.observability.langfuse import get_langfuse_callback_handler

logger = logging.getLogger("lyoko.chat_agent")

SYSTEM_PROMPT = """You are LYOKO, the Homelab AIOps assistant.
You help the administrator inspect Kubernetes clusters, Home Assistant smart devices, and UniFi network appliances.
Be concise, clear, and format all technical responses in clean Markdown."""


class InteractiveChatAgent:
    """Conversational assistant handling interactive user queries via chat connectors."""

    def __init__(self, mcp_client: Any, llm: Any | None = None) -> None:
        self.mcp_client = mcp_client
        if llm is not None:
            self.llm = llm
        else:
            try:
                self.llm = ChatOpenAI(model=settings.openai_model, temperature=0.2)
            except Exception as exc:
                logger.debug("ChatOpenAI could not be initialized directly: %s", exc)
                self.llm = None

    async def handle_message(self, message: IncomingMessage) -> str:
        """Process incoming chat query and return conversational response."""
        logger.info("Processing chat message from user %s: %s", message.user.user_id, message.text)
        if self.llm is None:
            return f"Received message: '{message.text}'. (LLM provider not configured)"

        langfuse_cb = get_langfuse_callback_handler()
        callbacks = [langfuse_cb] if langfuse_cb else []

        try:
            response = await self.llm.ainvoke(
                [
                    SystemMessage(content=SYSTEM_PROMPT),
                    HumanMessage(content=message.text),
                ],
                config={"callbacks": callbacks} if callbacks else None,
            )
            return str(response.content)
        except Exception as exc:
            logger.error("Failed to generate LLM response: %s", exc)
            return f"⚠️ Error processing your question: {exc}"
