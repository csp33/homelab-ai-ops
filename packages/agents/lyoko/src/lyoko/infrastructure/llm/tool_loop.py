"""ReAct tool-use loop for the OpenAI/LangChain LLM adapter.

Runs the bounded tool-calling loop with repeat detection, tool-call budget, and error-aware
nudges, then asks the model for a final summary when the loop ends.
"""

import json
import logging
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from lyoko.config import settings

logger = logging.getLogger("lyoko.infrastructure.llm.openai")

_ERROR_MARKERS = (
    "'is_error': true",
    '"is_error": true',
    '"is_error":true',
    "error executing tool",
    "not found on any upstream",
    "is forbidden:",
    "permission denied",
)
_MAX_CONSECUTIVE_TOOL_ERRORS = 3


def _bound_tool_output(output: Any) -> str:
    """Cap a single tool result so one call cannot dominate the context budget."""
    text = str(output)
    limit = settings.max_tool_output_chars
    if len(text) <= limit:
        return text
    return text[:limit] + "\n\n[System Note: Tool output truncated to fit the context budget.]"


def _is_tool_error(output: str) -> bool:
    """Detect a failed tool result so the loop can nudge a fix instead of blind retries."""
    lowered = output.lower()
    return any(marker in lowered for marker in _ERROR_MARKERS)


async def run_react_tool_loop(
    prompt_text: str,
    *,
    system_prompt: str | None,
    model_with_tools: Any,
    summary_client: Any,
    tools_by_name: dict[str, Any],
    max_iterations: int,
    on_token: Any,
) -> str:
    """Run the bounded ReAct loop until the model stops calling tools or a guardrail trips."""
    messages: list[Any] = []
    if system_prompt:
        messages.append(SystemMessage(content=system_prompt))
    messages.append(HumanMessage(content=prompt_text))

    tool_call_budget = settings.max_tool_calls_per_run
    executed_tool_calls = 0
    previous_tool_calls_sig: tuple[tuple[str, str], ...] | None = None
    consecutive_repeat_count = 0
    consecutive_tool_errors = 0
    last_error_fingerprint: str | None = None
    repeated_error_count = 0

    for step in range(max_iterations):
        if on_token is not None:
            accumulated_response = None
            accumulated_text: list[str] = []
            async for chunk in model_with_tools.astream(messages):
                accumulated_response = (
                    chunk if accumulated_response is None else accumulated_response + chunk
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
            (tc.get("name", ""), json.dumps(tc.get("args") or {}, sort_keys=True))
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

            if _is_tool_error(output_str):
                consecutive_tool_errors += 1
                fingerprint = f"{tool_name}|{output_str[:200]}"
                if fingerprint == last_error_fingerprint:
                    repeated_error_count += 1
                else:
                    repeated_error_count = 0
                last_error_fingerprint = fingerprint
                logger.warning(
                    "ReAct tool '%s' returned an error (%d consecutive).",
                    tool_name,
                    consecutive_tool_errors,
                )
                if repeated_error_count >= 1 or consecutive_tool_errors >= 2:
                    output_str += (
                        "\n\n[System Note: This tool keeps failing. Do not retry more "
                        "variants. Read its schema with gateway_get_tool_schema and supply "
                        "the missing or invalid argument, or switch to a different tool. "
                        "If the failure is a permissions error, report it instead of "
                        "retrying.]"
                    )
            else:
                consecutive_tool_errors = 0
                last_error_fingerprint = None
                repeated_error_count = 0

            messages.append(
                ToolMessage(
                    content=output_str,
                    tool_call_id=tool_call["id"],
                    name=tool_name,
                )
            )

        if budget_exceeded:
            break
        if consecutive_tool_errors >= _MAX_CONSECUTIVE_TOOL_ERRORS:
            logger.warning(
                "ReAct agent hit %d consecutive tool errors. Stopping for final summary.",
                consecutive_tool_errors,
            )
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
        async for chunk in summary_client.astream(messages):
            if chunk.content:
                text_piece = str(chunk.content)
                accumulated_content.append(text_piece)
                await on_token(text_piece)
        return "".join(accumulated_content)

    final_response = await summary_client.ainvoke(messages)
    return str(final_response.content)
