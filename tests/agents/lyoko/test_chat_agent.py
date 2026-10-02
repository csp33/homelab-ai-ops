"""Unit tests for LYOKO InteractiveChatAgent."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from lyoko.application.chat_agent import InteractiveChatAgent
from lyoko.domain.models.chat import ChatUser, IncomingMessage


@pytest.mark.asyncio
async def test_interactive_chat_agent_answers_query():
    """Verify that InteractiveChatAgent receives a message and returns LLM response."""
    mock_mcp = AsyncMock()
    mock_llm = AsyncMock()
    mock_llm_response = MagicMock()
    mock_llm_response.content = "All 5 pods are healthy in default namespace."
    mock_llm.ainvoke.return_value = mock_llm_response

    agent = InteractiveChatAgent(mcp_client=mock_mcp, llm=mock_llm)
    msg = IncomingMessage(
        message_id="1",
        chat_id="12345",
        user=ChatUser(user_id="12345", username="admin"),
        text="How is the cluster?",
    )
    reply = await agent.handle_message(msg)

    assert "healthy" in reply
    assert reply == "All 5 pods are healthy in default namespace."
    mock_llm.ainvoke.assert_awaited_once()
    call_args = mock_llm.ainvoke.call_args
    messages = call_args[0][0]
    assert len(messages) == 2
    assert messages[1].content == "How is the cluster?"


@pytest.mark.asyncio
async def test_interactive_chat_agent_handles_error():
    """Verify that InteractiveChatAgent catches exceptions and returns error message."""
    mock_mcp = AsyncMock()
    mock_llm = AsyncMock()
    mock_llm.ainvoke.side_effect = RuntimeError("OpenAI API rate limit exceeded")

    agent = InteractiveChatAgent(mcp_client=mock_mcp, llm=mock_llm)
    msg = IncomingMessage(
        message_id="2",
        chat_id="12345",
        user=ChatUser(user_id="12345", username="admin"),
        text="Can you restart nginx?",
    )
    reply = await agent.handle_message(msg)

    assert "⚠️ Error processing your question:" in reply
    assert "OpenAI API rate limit exceeded" in reply


@pytest.mark.asyncio
@patch("lyoko.application.chat_agent.get_langfuse_callback_handler")
async def test_interactive_chat_agent_with_langfuse_callback(mock_get_cb):
    """Verify that Langfuse callback handler is passed when available."""
    mock_cb = MagicMock()
    mock_get_cb.return_value = mock_cb

    mock_mcp = AsyncMock()
    mock_llm = AsyncMock()
    mock_llm_response = MagicMock()
    mock_llm_response.content = "Cluster is nominal."
    mock_llm.ainvoke.return_value = mock_llm_response

    agent = InteractiveChatAgent(mcp_client=mock_mcp, llm=mock_llm)
    msg = IncomingMessage(
        message_id="3",
        chat_id="12345",
        user=ChatUser(user_id="12345", username="admin"),
        text="Status check",
    )
    reply = await agent.handle_message(msg)

    assert reply == "Cluster is nominal."
    mock_llm.ainvoke.assert_awaited_once()
    call_kwargs = mock_llm.ainvoke.call_args[1]
    assert call_kwargs.get("config") == {"callbacks": [mock_cb]}


@patch("lyoko.application.chat_agent.ChatOpenAI")
def test_interactive_chat_agent_default_llm(mock_chat_openai_cls):
    """Verify default ChatOpenAI initialization when llm is not provided."""
    mock_mcp = AsyncMock()
    agent = InteractiveChatAgent(mcp_client=mock_mcp)

    mock_chat_openai_cls.assert_called_once()
    assert agent.mcp_client is mock_mcp
    assert agent.llm is mock_chat_openai_cls.return_value
