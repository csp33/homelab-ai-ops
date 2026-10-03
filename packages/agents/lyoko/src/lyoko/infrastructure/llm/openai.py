"""OpenAI / LangChain LLM infrastructure adapter for LYOKO."""

import logging
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableLambda
from langchain_openai import ChatOpenAI
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
        underlying loop raises instead of looping forever.

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
                tools_by_name = {tool.name: tool for tool in tools}
                model_with_tools = self.client.bind_tools(tools)
                max_iterations = max_steps or 10

                async def _react_loop(prompt_text: str) -> str:
                    messages: list[Any] = []
                    if system_prompt:
                        messages.append(SystemMessage(content=system_prompt))
                    messages.append(HumanMessage(content=prompt_text))

                    for step_idx in range(max_iterations):
                        response = await model_with_tools.ainvoke(messages)
                        messages.append(response)

                        if not response.tool_calls:
                            return str(response.content)

                        for tool_call in response.tool_calls:
                            tool_name = tool_call["name"]
                            tool_args = tool_call["args"]
                            logger.info(
                                "ReAct step %d/%d: calling '%s' with %s",
                                step_idx + 1,
                                max_iterations,
                                tool_name,
                                tool_args,
                            )
                            tool = tools_by_name.get(tool_name)
                            if tool is None:
                                tool_output = f"Error: Tool '{tool_name}' not found."
                            else:
                                try:
                                    if hasattr(tool, "ainvoke"):
                                        tool_output = await tool.ainvoke(tool_args)
                                    else:
                                        tool_output = tool.invoke(tool_args)
                                except Exception as exc:
                                    tool_output = f"Error executing tool '{tool_name}': {exc}"

                            messages.append(
                                ToolMessage(
                                    content=str(tool_output),
                                    tool_call_id=tool_call["id"],
                                    name=tool_name,
                                )
                            )

                    raise RuntimeError(f"Agent exceeded maximum allowed steps ({max_iterations})")

                loop_runnable = RunnableLambda(_react_loop, name=trace_name or "chat-agent")
                return await loop_runnable.ainvoke(prompt, config=config if config else None)
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
