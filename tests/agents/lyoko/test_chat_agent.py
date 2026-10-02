"""Unit tests for LYOKO InteractiveChatAgent."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from lyoko.application.chat_agent import InteractiveChatAgent
from lyoko.application.chat_sessions import ChatSessionTracker
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
    assert call_kwargs.get("session_id").startswith("telegram-12345-")
    assert call_kwargs.get("user_id") == "12345"
    assert call_kwargs.get("trace_name") == "telegram-chat-interaction"
    assert "telegram" in call_kwargs.get("tags", [])


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


def _make_agent_with_clock(now: list[datetime]) -> tuple[InteractiveChatAgent, AsyncMock]:
    mock_llm = AsyncMock(spec=LLMClientInterface)
    mock_llm.chat.return_value = "ok"
    tracker = ChatSessionTracker(idle_timeout_seconds=900, clock=lambda: now[0])
    mcp_client = MagicMock()
    mcp_client.get_langchain_tools.return_value = []
    agent = InteractiveChatAgent(mcp_client=mcp_client, llm=mock_llm, session_tracker=tracker)
    return agent, mock_llm


def _msg(text: str, message_id: str = "1", reply_to: str | None = None) -> IncomingMessage:
    return IncomingMessage(
        message_id=message_id,
        chat_id="42",
        user=ChatUser(user_id="42", username="admin"),
        text=text,
        reply_to_message_id=reply_to,
    )


@pytest.mark.asyncio
async def test_new_command_starts_fresh_session_without_calling_llm():
    """/new rotates the session and does not spend an LLM call."""
    now = [datetime(2026, 10, 2, 20, 0, 0, tzinfo=UTC)]
    agent, llm = _make_agent_with_clock(now)

    await agent.handle_message(_msg("first topic"))
    first_session = llm.chat.call_args[1]["session_id"]

    now[0] += timedelta(seconds=30)
    reply = await agent.handle_message(_msg("/new"))
    assert "new session" in reply.lower()
    assert llm.chat.await_count == 1

    now[0] += timedelta(seconds=30)
    await agent.handle_message(_msg("second topic"))
    second_session = llm.chat.call_args[1]["session_id"]

    assert first_session != second_session


@pytest.mark.asyncio
async def test_new_command_with_bot_mention_is_recognized():
    now = [datetime(2026, 10, 2, 20, 0, 0, tzinfo=UTC)]
    agent, llm = _make_agent_with_clock(now)

    reply = await agent.handle_message(_msg("/new@lyoko_bot"))

    assert "new session" in reply.lower()
    llm.chat.assert_not_awaited()


@pytest.mark.asyncio
async def test_reply_to_linked_alert_message_uses_incident_session():
    """Replying to an alert message continues that incident's session."""
    now = [datetime(2026, 10, 2, 20, 0, 0, tzinfo=UTC)]
    agent, llm = _make_agent_with_clock(now)
    agent.session_tracker.link_message("42", "900", "incident-abc123")

    await agent.handle_message(_msg("why did it die?", message_id="901", reply_to="900"))
    assert llm.chat.call_args[1]["session_id"] == "incident-abc123"

    # A follow-up without an explicit reply stays in the incident session.
    now[0] += timedelta(minutes=2)
    await agent.handle_message(_msg("and the logs?", message_id="902"))
    assert llm.chat.call_args[1]["session_id"] == "incident-abc123"
