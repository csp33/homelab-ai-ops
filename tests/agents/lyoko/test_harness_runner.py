"""Unit tests for ReActHarnessRunner."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import ToolMessage
from lyoko.application.context.buffer import SmartOutputBufferService
from lyoko.domain.models.scratchpad import SmartBufferConfig
from lyoko.infrastructure.llm.harness_runner import ReActHarnessRunner
from lyoko.infrastructure.storage.scratchpad_file_storage import ScratchpadFileStorage


@pytest.mark.asyncio
async def test_harness_runner_offloads_massive_output(tmp_path: Path):
    storage = ScratchpadFileStorage(base_dir=tmp_path)
    config = SmartBufferConfig(max_chars=200, offload_threshold_chars=500, head_ratio=0.25)
    buffer = SmartOutputBufferService(storage=storage, config=config)
    runner = ReActHarnessRunner(buffer_service=buffer)

    tool_call_msg = MagicMock()
    tool_call_msg.tool_calls = [{"name": "k8s_logs", "args": {"pod": "crashpod"}, "id": "call_1"}]

    final_msg = MagicMock()
    final_msg.tool_calls = []
    final_msg.content = "Analysis completed."

    model_with_tools = AsyncMock()
    model_with_tools.ainvoke.side_effect = [tool_call_msg, final_msg]

    mock_tool = MagicMock()
    mock_tool.name = "k8s_logs"
    mock_tool.ainvoke = AsyncMock(return_value="START_" + ("ERR_" * 200) + "_END")

    summary_client = MagicMock()

    result = await runner.run(
        prompt_text="Investigate pod crash",
        system_prompt="You are Lyoko",
        model_with_tools=model_with_tools,
        summary_client=summary_client,
        tools_by_name={"k8s_logs": mock_tool},
        max_iterations=5,
        session_id="incident-99",
    )

    assert result == "Analysis completed."

    # Verify that the tool message received the scratchpad note
    second_call_messages = model_with_tools.ainvoke.call_args_list[1].args[0]
    tool_messages = [m for m in second_call_messages if isinstance(m, ToolMessage)]
    assert len(tool_messages) == 1
    assert "saved to scratchpad file:" in tool_messages[0].content

    files = list(tmp_path.glob("scratch_*_k8s_logs.log"))
    assert len(files) == 1
