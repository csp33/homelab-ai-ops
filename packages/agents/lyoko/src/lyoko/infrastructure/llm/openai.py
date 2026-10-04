"""OpenAI / LangChain LLM infrastructure adapter for LYOKO."""

import json
import logging
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableLambda
from langchain_openai import ChatOpenAI
from lyoko.config import settings
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


def _bound_tool_output(output: Any) -> str:
    """Cap a single tool result so one call cannot dominate the context budget."""
    text = str(output)
    limit = settings.max_tool_output_chars
    if len(text) <= limit:
        return text
    return text[:limit] + "\n\n[System Note: Tool output truncated to fit the context budget.]"


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
        on_token: Any = None,
    ) -> str:
        """Process conversational prompt with optional tools, Langfuse session, user, and tracing.

        ``max_steps`` bounds the tool-use iterations of the ReAct agent. When exceeded, the
        underlying loop raises instead of looping forever.

        With ``parent_config`` the call joins the trace of the enclosing graph run as a child
        span named ``trace_name``. Without it, a new trace is started.

        ``on_token`` is an optional async callback invoked as text tokens are streamed.
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

                    tool_call_budget = settings.max_tool_calls_per_run
                    executed_tool_calls = 0
                    previous_tool_calls_sig: tuple[tuple[str, str], ...] | None = None
                    consecutive_repeat_count = 0

                    for step in range(max_iterations):
                        if on_token is not None:
                            accumulated_response = None
                            accumulated_text: list[str] = []
                            async for chunk in model_with_tools.astream(messages):
                                accumulated_response = (
                                    chunk
                                    if accumulated_response is None
                                    else accumulated_response + chunk
                                )
                                if chunk.content:
                                    text_piece = str(chunk.content)
                                    accumulated_text.append(text_piece)
                                    await on_token(text_piece)
                            response = accumulated_response
                        else:
                            response = await model_with_tools.ainvoke(messages)

                        if response is None:
                            response = await model_with_tools.ainvoke(messages)

                        messages.append(response)

                        if not response.tool_calls:
                            return str(response.content)

                        current_tool_calls_sig = tuple(
                            (
                                tc.get("name", ""),
                                json.dumps(tc.get("args") or {}, sort_keys=True),
                            )
                            for tc in response.tool_calls
                        )

                        if current_tool_calls_sig == previous_tool_calls_sig:
                            consecutive_repeat_count += 1
                        else:
                            consecutive_repeat_count = 0
                        previous_tool_calls_sig = current_tool_calls_sig

                        if consecutive_repeat_count >= 2:
                            logger.warning(
                                "ReAct agent repeated identical tool calls %d times consecutively. "
                                "Breaking loop to prevent runaway token cost.",
                                consecutive_repeat_count + 1,
                            )
                            break

                        budget_exceeded = False
                        for tool_call in response.tool_calls:
                            tool_name = tool_call["name"]
                            tool_args = tool_call["args"]

                            if executed_tool_calls >= tool_call_budget:
                                logger.warning(
                                    "ReAct agent reached the tool-call budget (%d); skipping '%s'.",
                                    tool_call_budget,
                                    tool_name,
                                )
                                budget_exceeded = True
                                messages.append(
                                    ToolMessage(
                                        content=(
                                            "[System Note: Tool-call budget reached for this run. "
                                            "This call was not executed; summarize your findings now "
                                            "without further tool calls.]"
                                        ),
                                        tool_call_id=tool_call["id"],
                                        name=tool_name,
                                    )
                                )
                                continue

                            executed_tool_calls += 1
                            logger.info(
                                "ReAct step %d/%d: calling '%s' with %s",
                                step + 1,
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

                            output_str = _bound_tool_output(tool_output)
                            if consecutive_repeat_count == 1:
                                output_str += (
                                    "\n\n[System Note: This tool was called with the exact same "
                                    "arguments in the previous step. If no resources were returned, "
                                    "conclude that they do not exist instead of repeating identical queries.]"
                                )

                            messages.append(
                                ToolMessage(
                                    content=output_str,
                                    tool_call_id=tool_call["id"],
                                    name=tool_name,
                                )
                            )

                        if budget_exceeded:
                            break

                    logger.warning(
                        "ReAct agent reached maximum allowed steps (%d) or stopped loop. Requesting final summary.",
                        max_iterations,
                    )
                    messages.append(
                        HumanMessage(
                            content="You have reached the maximum allowed steps. Please summarize your findings, actions taken, and current status based on the information gathered so far without making further tool calls."
                        )
                    )
                    if on_token is not None:
                        accumulated_content: list[str] = []
                        async for chunk in self.client.astream(messages):
                            if chunk.content:
                                text_piece = str(chunk.content)
                                accumulated_content.append(text_piece)
                                await on_token(text_piece)
                        return "".join(accumulated_content)

                    final_response = await self.client.ainvoke(messages)
                    return str(final_response.content)

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

        if on_token is not None:
            accumulated_content = []
            async for chunk in self.client.astream(messages, config=config if config else None):
                if chunk.content:
                    text_piece = str(chunk.content)
                    accumulated_content.append(text_piece)
                    await on_token(text_piece)
            return "".join(accumulated_content)

        response = await self.client.ainvoke(messages, config=config if config else None)
        return str(response.content)
