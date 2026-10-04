from unittest.mock import AsyncMock, MagicMock

import pytest
from lyoko.domain.models.chat import (
    ApprovalAction,
    ApprovalRequest,
    IncomingMessage,
)
from lyoko.infrastructure.chat.telegram import TelegramConnector


@pytest.mark.asyncio
async def test_telegram_connector_incoming_message_handler():
    connector = TelegramConnector(
        bot_token="fake:token", allowed_user_ids={"12345"}, default_chat_id="12345"
    )
    received_msgs: list[IncomingMessage] = []

    async def handler(msg: IncomingMessage) -> str:
        received_msgs.append(msg)
        return "Acknowledged"

    connector.register_message_handler(handler)

    mock_update = MagicMock()
    mock_update.effective_user.id = 12345
    mock_update.effective_user.username = "admin"
    mock_update.effective_user.first_name = "Admin"
    mock_update.effective_chat.id = 12345
    mock_update.message.message_id = 42
    mock_update.message.message_thread_id = None
    mock_update.message.text = "/status"
    mock_update.message.set_reaction = AsyncMock()
    mock_update.message.reply_text = AsyncMock()

    await connector._handle_telegram_message(mock_update, MagicMock())

    assert len(received_msgs) == 1
    assert received_msgs[0].text == "/status"
    assert received_msgs[0].user.user_id == "12345"
    assert received_msgs[0].user.username == "admin"
    mock_update.message.set_reaction.assert_called_once_with(reaction="👀")
    mock_update.message.reply_text.assert_called_once_with(
        "Acknowledged",
        parse_mode="HTML",
        reply_to_message_id=42,
        message_thread_id=None,
        allow_sending_without_reply=True,
    )


@pytest.mark.asyncio
async def test_telegram_connector_reaction_failure_is_logged_and_does_not_block_reply(caplog):
    connector = TelegramConnector(
        bot_token="fake:token", allowed_user_ids={"12345"}, default_chat_id="12345"
    )

    async def handler(msg: IncomingMessage) -> str:
        return "Acknowledged"

    connector.register_message_handler(handler)

    mock_update = MagicMock()
    mock_update.effective_user.id = 12345
    mock_update.effective_user.username = "admin"
    mock_update.effective_user.first_name = "Admin"
    mock_update.effective_chat.id = 12345
    mock_update.message.message_id = 43
    mock_update.message.text = "top 10 clients"
    mock_update.message.set_reaction = AsyncMock(side_effect=RuntimeError("REACTION_INVALID"))
    mock_update.message.reply_text = AsyncMock()

    with caplog.at_level("WARNING", logger="lyoko.chat.telegram"):
        await connector._handle_telegram_message(mock_update, MagicMock())

    assert "Failed to set" in caplog.text
    assert "REACTION_INVALID" in caplog.text
    assert "43" in caplog.text
    mock_update.message.reply_text.assert_called_once()


@pytest.mark.asyncio
async def test_telegram_connector_message_handler_exception():
    connector = TelegramConnector(
        bot_token="fake:token", allowed_user_ids={"12345"}, default_chat_id="12345"
    )

    async def failing_handler(msg: IncomingMessage) -> str:
        raise ValueError("Handler crash")

    connector.register_message_handler(failing_handler)

    mock_update = MagicMock()
    mock_update.effective_user.id = 12345
    mock_update.effective_user.username = "admin"
    mock_update.effective_user.first_name = "Admin"
    mock_update.effective_chat.id = 12345
    mock_update.message.message_id = 44
    mock_update.message.text = "/crash"
    mock_update.message.reply_text = AsyncMock()

    await connector._handle_telegram_message(mock_update, MagicMock())

    mock_update.message.reply_text.assert_called_once()
    assert "Error processing request" in mock_update.message.reply_text.call_args[0][0]


@pytest.mark.asyncio
async def test_telegram_connector_populates_reply_to_message_id():
    connector = TelegramConnector(
        bot_token="fake:token", allowed_user_ids={"12345"}, default_chat_id="12345"
    )
    received: list[IncomingMessage] = []

    async def handler(msg: IncomingMessage) -> None:
        received.append(msg)

    connector.register_message_handler(handler)

    update = MagicMock()
    update.effective_user.id = 12345
    update.effective_chat.id = 12345
    update.message.message_id = 50
    update.message.text = "why did it crash?"
    update.message.reply_to_message.message_id = 41
    update.message.set_reaction = AsyncMock()
    update.message.reply_text = AsyncMock()

    await connector._handle_telegram_message(update, MagicMock())

    assert received[0].reply_to_message_id == "41"


@pytest.mark.asyncio
async def test_telegram_connector_send_returns_message_reference():
    connector = TelegramConnector(bot_token="fake:token", default_chat_id="12345")
    sent = MagicMock()
    sent.message_id = 777
    sent.chat_id = 12345
    mock_app = MagicMock()
    mock_app.bot.send_message = AsyncMock(return_value=sent)
    connector._app = mock_app

    result = await connector.send_message("12345", "hello")
    assert result is not None
    assert (result.chat_id, result.message_id) == ("12345", "777")

    approval = await connector.send_approval_request(
        ApprovalRequest(
            incident_id="inc-1",
            title="t",
            details="d",
            chat_id="12345",
            actions=[ApprovalAction(action_id="approve", label="Approve")],
        )
    )
    assert approval is not None
    assert approval.message_id == "777"


@pytest.mark.asyncio
async def test_telegram_connector_channel_post_redirects_to_discussion_group():
    """Verify replies to channel posts are sent into the linked discussion group comment thread."""
    connector = TelegramConnector(
        bot_token="fake:token",
        allowed_user_ids=set(),
        allowed_chat_ids={"-1001234567890", "-1004400196957"},
        default_chat_id="-1001234567890",
        discussion_group_id="-1004400196957",
    )

    async def handler(msg: IncomingMessage) -> str:
        return "Reply in thread"

    connector.register_message_handler(handler)

    mock_app = MagicMock()
    mock_app.bot.send_message = AsyncMock(
        return_value=MagicMock(message_id=999, chat_id="-1004400196957")
    )
    connector._app = mock_app

    # 1. Simulate the automatic forward of the channel post arriving in the discussion group
    forward_msg = MagicMock()
    forward_msg.message_id = 200
    forward_origin = MagicMock()
    forward_origin.type = "channel"
    forward_origin.chat.id = -1001234567890
    forward_origin.message_id = 50
    forward_msg.forward_origin = forward_origin

    connector._record_channel_forward(forward_msg)

    # 2. Simulate user posting in channel
    channel_update = MagicMock()
    channel_update.message = None
    channel_update.effective_chat.id = -1001234567890
    channel_update.effective_chat.type = "channel"
    channel_update.effective_user = None
    channel_update.effective_message.message_id = 50
    channel_update.effective_message.message_thread_id = None
    channel_update.effective_message.text = "Hello from channel"
    channel_update.effective_message.is_automatic_forward = False
    channel_update.effective_message.set_reaction = AsyncMock()
    channel_update.effective_message.reply_text = AsyncMock()

    await connector._handle_telegram_message(channel_update, MagicMock())

    # Reply should NOT be sent to channel via reply_text
    channel_update.effective_message.reply_text.assert_not_called()

    # Reply MUST be sent to discussion group with reply_to_message_id=200
    mock_app.bot.send_message.assert_called_once()
    call_kwargs = mock_app.bot.send_message.call_args[1]
    assert call_kwargs["chat_id"] == "-1004400196957"
    assert call_kwargs["reply_to_message_id"] == 200
    assert call_kwargs["message_thread_id"] == 200
    assert "Reply in thread" in call_kwargs["text"]
