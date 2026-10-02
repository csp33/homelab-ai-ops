"""Unit tests for OpenAILLMAdapter infrastructure adapter."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
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
@patch("lyoko.infrastructure.llm.openai.get_langfuse_callback_handler")
async def test_openai_llm_adapter_with_langfuse_callback(mock_get_cb):
    """Verify Langfuse callback is attached when available."""
    mock_cb = MagicMock()
    mock_get_cb.return_value = mock_cb

    adapter = OpenAILLMAdapter(api_key="sk-test")
    mock_client = AsyncMock()
    mock_response = MagicMock()
    mock_response.content = "All green."
    mock_client.ainvoke.return_value = mock_response
    adapter._client = mock_client

    result = await adapter.chat(prompt="Status check")
    assert result == "All green."
    config = mock_client.ainvoke.call_args[1].get("config")
    assert config == {"callbacks": [mock_cb]}


@pytest.mark.asyncio
async def test_openai_llm_adapter_analyze_incident():
    """Verify analyze_incident formats diagnostic prompt."""
    adapter = OpenAILLMAdapter(api_key="sk-test")
    mock_client = AsyncMock()
    mock_response = MagicMock()
    mock_response.content = "Root cause: OOMKilled."
    mock_client.ainvoke.return_value = mock_response
    adapter._client = mock_client

    result = await adapter.analyze_incident(
        alert_name="KubePodCrashLooping",
        pod_name="api-deployment-xyz",
        namespace="production",
        diagnostics={"exit_code": 137},
    )

    assert result == "Root cause: OOMKilled."
    mock_client.ainvoke.assert_awaited_once()
    prompt_text = mock_client.ainvoke.call_args[0][0][1].content
    assert "KubePodCrashLooping" in prompt_text
    assert "api-deployment-xyz" in prompt_text
    assert "production" in prompt_text


@pytest.mark.asyncio
async def test_openai_llm_adapter_generate_remediation_plan():
    """Verify generate_remediation_plan formats context."""
    adapter = OpenAILLMAdapter(api_key="sk-test")
    mock_client = AsyncMock()
    mock_response = MagicMock()
    mock_response.content = "1. Bump memory limit to 1Gi"
    mock_client.ainvoke.return_value = mock_response
    adapter._client = mock_client

    result = await adapter.generate_remediation_plan({"pod": "api", "memory": "512Mi"})
    assert "1. Bump memory" in result
