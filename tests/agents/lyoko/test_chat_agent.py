"""Unit tests for LYOKO InteractiveChatAgent."""

from unittest.mock import AsyncMock

import pytest
from lyoko.application.chat_agent import InteractiveChatAgent
from lyoko.domain.interfaces.llm import LLMClientInterface
from lyoko.domain.models.chat import ChatUser, IncomingMessage


@pytest.mark.asyncio
async def test_interactive_chat_agent_answers_query():
    """Verify that InteractiveChatAgent receives a message and returns LLM response."""
    mock_mcp = AsyncMock()
    mock_llm = AsyncMock(spec=LLMClientInterface)
    mock_llm.chat.return_value = "All 5 pods are healthy in default namespace."

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
    mock_llm.chat.assert_awaited_once()
    call_kwargs = mock_llm.chat.call_args[1]
    assert call_kwargs.get("prompt") == "How is the cluster?"


@pytest.mark.asyncio
async def test_interactive_chat_agent_handles_error():
    """Verify that InteractiveChatAgent catches exceptions and returns error message."""
    mock_mcp = AsyncMock()
    mock_llm = AsyncMock(spec=LLMClientInterface)
    mock_llm.chat.side_effect = RuntimeError("OpenAI API rate limit exceeded")

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
async def test_interactive_chat_agent_without_llm():
    """Verify behavior when LLM is not configured."""
    mock_mcp = AsyncMock()
    agent = InteractiveChatAgent(mcp_client=mock_mcp, llm=None)
    msg = IncomingMessage(
        message_id="3",
        chat_id="12345",
        user=ChatUser(user_id="12345", username="admin"),
        text="Ping",
    )
    reply = await agent.handle_message(msg)
    assert "LLM provider not configured" in reply
