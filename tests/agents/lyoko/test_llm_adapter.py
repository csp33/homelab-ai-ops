"""Unit tests for OpenAILLMAdapter infrastructure adapter."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.callbacks import BaseCallbackHandler
from lyoko.infrastructure.llm.openai import OpenAILLMAdapter


@pytest.mark.asyncio
async def test_openai_llm_adapter_chat():
    """Verify chat invocation delegates to ChatOpenAI with proper messages."""
    adapter = OpenAILLMAdapter(api_key="sk-test", model_name="gpt-4o-mini")
    mock_client = AsyncMock()
    mock_response = MagicMock()
    mock_response.content = "Everything is running smoothly."
    mock_client.ainvoke.return_value = mock_response
    adapter._client = mock_client

    result = await adapter.chat(prompt="How is the cluster?", system_prompt="You are LYOKO.")
    assert result == "Everything is running smoothly."
    mock_client.ainvoke.assert_awaited_once()

    messages = mock_client.ainvoke.call_args[0][0]
    assert len(messages) == 2
    assert messages[0].content == "You are LYOKO."
    assert messages[1].content == "How is the cluster?"


@pytest.mark.asyncio
@patch("lyoko.infrastructure.llm.openai.get_langfuse_trace_config")
async def test_openai_llm_adapter_with_langfuse_callback(mock_get_config):
    """Verify Langfuse trace config is attached when available."""
    mock_get_config.return_value = {
        "callbacks": ["mock_cb"],
        "metadata": {"langfuse_session_id": "telegram-123"},
    }

    adapter = OpenAILLMAdapter(api_key="sk-test")
    mock_client = AsyncMock()
    mock_response = MagicMock()
    mock_response.content = "All green."
    mock_client.ainvoke.return_value = mock_response
    adapter._client = mock_client

    result = await adapter.chat(
        prompt="Status check",
        session_id="telegram-123",
        user_id="user-456",
    )
    assert result == "All green."
    config = mock_client.ainvoke.call_args[1].get("config")
    assert config == {"callbacks": ["mock_cb"], "metadata": {"langfuse_session_id": "telegram-123"}}
    mock_get_config.assert_called_once_with(
        session_id="telegram-123",
        user_id="user-456",
        trace_name="telegram-chat-interaction",
        tags=["telegram", "chat-agent"],
        metadata=None,
    )


@pytest.mark.asyncio
async def test_openai_llm_adapter_bounds_agent_steps():
    """max_steps limits the tool-use loop iterations and raises when exceeded."""
    tool_call_msg = MagicMock()
    tool_call_msg.tool_calls = [{"name": "mock_tool", "args": {}, "id": "call_1"}]
    mock_bound_client = AsyncMock()
    mock_bound_client.ainvoke.return_value = tool_call_msg

    adapter = OpenAILLMAdapter(api_key="sk-test")
    mock_client = MagicMock()
    mock_client.bind_tools.return_value = mock_bound_client
    adapter._client = mock_client

    mock_tool = MagicMock()
    mock_tool.name = "mock_tool"
    mock_tool.ainvoke = AsyncMock(return_value="tool_result")

    with pytest.raises(RuntimeError, match="Agent exceeded maximum allowed steps"):
        await adapter.chat(prompt="Investigate", tools=[mock_tool], max_steps=3)

    assert mock_bound_client.ainvoke.await_count == 3


@pytest.mark.asyncio
@patch("lyoko.infrastructure.llm.openai.get_langfuse_trace_config")
async def test_openai_llm_adapter_step_bound_keeps_trace_config(mock_get_config):
    mock_cb = BaseCallbackHandler()
    mock_get_config.return_value = {"callbacks": [mock_cb]}
    resp_msg = MagicMock()
    resp_msg.tool_calls = []
    resp_msg.content = "done"

    mock_bound_client = AsyncMock()
    mock_bound_client.ainvoke.return_value = resp_msg

    adapter = OpenAILLMAdapter(api_key="sk-test")
    mock_client = MagicMock()
    mock_client.bind_tools.return_value = mock_bound_client
    adapter._client = mock_client

    result = await adapter.chat(prompt="Investigate", tools=[MagicMock()], max_steps=3)
    assert result == "done"
    mock_get_config.assert_called_once()


@pytest.mark.asyncio
async def test_nested_agent_joins_the_parent_trace_instead_of_starting_one():
    resp_msg = MagicMock()
    resp_msg.tool_calls = []
    resp_msg.content = "done"

    mock_bound_client = AsyncMock()
    mock_bound_client.ainvoke.return_value = resp_msg

    adapter = OpenAILLMAdapter(api_key="sk-test")
    mock_client = MagicMock()
    mock_client.bind_tools.return_value = mock_bound_client
    adapter._client = mock_client

    mock_cb = BaseCallbackHandler()
    parent = {
        "callbacks": [mock_cb],
        "configurable": {"thread_id": "t1", "checkpoint_ns": "diagnose:1"},
        "recursion_limit": 3,
        "run_name": "lyoko",
    }

    result = await adapter.chat(
        prompt="Investigate",
        tools=[MagicMock()],
        trace_name="diagnose-agent",
        tags=["phase:diagnose"],
        max_steps=10,
        parent_config=parent,
    )

    assert result == "done"


@pytest.mark.asyncio
@patch("lyoko.infrastructure.llm.openai.get_langfuse_trace_config")
async def test_nested_call_without_tools_joins_the_parent_trace(mock_get_config):
    adapter = OpenAILLMAdapter(api_key="sk-test")
    client = AsyncMock()
    client.ainvoke.return_value = MagicMock(content="CHAT")
    adapter._client = client

    result = await adapter.chat(
        prompt="hi",
        trace_name="route-llm",
        tags=["phase:route"],
        session_id="ignored",
        parent_config={"callbacks": ["parent_cb"], "configurable": {"thread_id": "t"}},
    )

    assert result == "CHAT"
    mock_get_config.assert_not_called()
    assert client.ainvoke.call_args.kwargs["config"] == {
        "callbacks": ["parent_cb"],
        "run_name": "route-llm",
        "tags": ["phase:route"],
    }


@pytest.mark.asyncio
@patch("lyoko.infrastructure.llm.openai.get_langfuse_trace_config")
async def test_nested_call_works_when_the_parent_has_no_tracer(mock_get_config):
    adapter = OpenAILLMAdapter(api_key="sk-test")
    client = AsyncMock()
    client.ainvoke.return_value = MagicMock(content="CHAT")
    adapter._client = client

    await adapter.chat(prompt="hi", trace_name="route-llm", parent_config={})

    assert client.ainvoke.call_args.kwargs["config"] == {"run_name": "route-llm"}
