from typing import Any

from lyoko.config import settings
from lyoko.infrastructure.llm.harness_runner import ReActHarnessRunner

_runner = ReActHarnessRunner()
_tool_status = _runner._tool_status
_detect_cycle = _runner._detect_cycle


def _bound_tool_output(output: Any) -> str:
    text = str(output)
    limit = settings.max_tool_output_chars
    if len(text) <= limit:
        return text
    return text[:limit] + "\n\n[System Note: Tool output truncated to fit the context budget.]"


async def run_react_tool_loop(
    prompt_text: str,
    *,
    system_prompt: str | None,
    model_with_tools: Any,
    summary_client: Any,
    tools_by_name: dict[str, Any],
    max_iterations: int,
    session_id: str | None = None,
    on_status: Any = None,
) -> str:
    """Run bounded ReAct loop via ReActHarnessRunner."""
    return await _runner.run(
        prompt_text=prompt_text,
        system_prompt=system_prompt,
        model_with_tools=model_with_tools,
        summary_client=summary_client,
        tools_by_name=tools_by_name,
        max_iterations=max_iterations,
        session_id=session_id,
        on_status=on_status,
    )
