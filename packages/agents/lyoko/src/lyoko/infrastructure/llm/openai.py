"""OpenAI / LangChain LLM infrastructure adapter for LYOKO."""

import logging
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent
from lyoko.domain.interfaces.llm import LLMClientInterface
from lyoko.infrastructure.observability.langfuse import get_langfuse_trace_config

logger = logging.getLogger("lyoko.infrastructure.llm.openai")


def _child_config(
    parent_config: dict[str, Any],
    name: str | None,
    tags: list[str] | None,
    metadata: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build the run config of a call nested in an already traced graph run.

    Only the callbacks are taken from the parent, so the call becomes a child span of it. The
    rest of the parent config (``configurable``, checkpoint state, recursion limit) belongs to the
    parent graph and must not leak into this one.
    """
    config: dict[str, Any] = {}
    if parent_config.get("callbacks") is not None:
        config["callbacks"] = parent_config["callbacks"]
    if name:
        config["run_name"] = name
    if tags:
        config["tags"] = list(tags)
    if metadata:
        config["metadata"] = dict(metadata)
    return config


class OpenAILLMAdapter(LLMClientInterface):
    """LLM adapter implementing LLMClientInterface backed by ChatOpenAI and LangChain."""

    def __init__(
        self,
        api_key: str | None = None,
        model_name: str = "gpt-4o-mini",
        temperature: float = 0.0,
    ) -> None:
        self.model_name = model_name
        self.temperature = temperature
        self._api_key = api_key
        self._client: ChatOpenAI | None = None

    @property
    def client(self) -> ChatOpenAI:
        if self._client is None:
            api_key = self._api_key or "sk-dummy"
            self._client = ChatOpenAI(
                model=self.model_name,
                temperature=self.temperature,
                api_key=api_key,
            )
        return self._client

    async def chat(
        self,
        prompt: str,
        system_prompt: str | None = None,
        tools: list[Any] | None = None,
        session_id: str | None = None,
        user_id: str | None = None,
        trace_name: str | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        max_steps: int | None = None,
        parent_config: dict[str, Any] | None = None,
    ) -> str:
        """Process conversational prompt with optional tools, Langfuse session, user, and tracing.

        ``max_steps`` bounds the tool-use iterations of the ReAct agent. When exceeded, the
        underlying graph raises instead of looping forever.

        With ``parent_config`` the call joins the trace of the enclosing graph run as a child
        span named ``trace_name``. Without it, a new trace is started.
        """
        if parent_config is not None:
            config = _child_config(parent_config, trace_name, tags, metadata)
        else:
            config = get_langfuse_trace_config(
                session_id=session_id,
                user_id=user_id,
                trace_name=trace_name or "telegram-chat-interaction",
                tags=tags or ["telegram", "chat-agent"],
                metadata=metadata,
            )

        if tools:
            try:
                agent = create_react_agent(
                    model=self.client,
                    tools=tools,
                    prompt=system_prompt,
                )
                messages = [HumanMessage(content=prompt)]
                agent_config = dict(config) if config else {}
                if max_steps is not None:
                    # Each tool-use iteration takes two graph steps (model, then tools).
                    agent_config["recursion_limit"] = max_steps * 2 + 1
                result = await agent.ainvoke(
                    {"messages": messages},
                    config=agent_config or None,
                )
                last_message = result["messages"][-1]
                return str(last_message.content)
            except Exception as e:
                # Never fall back to a tool-less chat: the system prompt forbids answering about
                # live infrastructure without tools, so a silent fallback produces hallucinations.
                logger.error("Error executing ReAct agent with tools: %s", e, exc_info=True)
                raise

        messages: list[Any] = []
        if system_prompt:
            messages.append(SystemMessage(content=system_prompt))
        messages.append(HumanMessage(content=prompt))

        response = await self.client.ainvoke(messages, config=config if config else None)
        return str(response.content)
