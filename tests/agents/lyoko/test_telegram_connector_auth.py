from unittest.mock import AsyncMock, MagicMock

import pytest
from lyoko.domain.models.chat import (
    IncomingMessage,
)
from lyoko.infrastructure.chat.telegram import TelegramConnector
from pydantic import SecretStr


@pytest.mark.asyncio
async def test_telegram_connector_whitelist_authorization():
    connector = TelegramConnector(
        bot_token="fake:token", allowed_user_ids={"12345"}, default_chat_id="12345"
    )
    assert connector.is_user_authorized("12345") is True
    assert connector.is_user_authorized(12345) is True
    assert connector.is_user_authorized("99999") is False
    assert connector.is_user_authorized(None) is False

    # String comma-separated
    connector_csv = TelegramConnector(
        bot_token=SecretStr("fake:token"), allowed_user_ids="111, 222 ,333"
    )
    assert connector_csv.is_user_authorized("111") is True
    assert connector_csv.is_user_authorized("222") is True
    assert connector_csv.is_user_authorized("333") is True
    assert connector_csv.is_user_authorized("444") is False

    # Empty whitelist should deny all
    empty_connector = TelegramConnector(bot_token="fake:token", allowed_user_ids=set())
    assert empty_connector.is_user_authorized("12345") is False


@pytest.mark.asyncio
async def test_telegram_connector_unauthorized_message():
    connector = TelegramConnector(
        bot_token="fake:token", allowed_user_ids={"12345"}, default_chat_id="12345"
    )
    mock_handler = AsyncMock()
    connector.register_message_handler(mock_handler)

    mock_update = MagicMock()
    mock_update.effective_user.id = 99999
    mock_update.effective_chat.id = 99999
    mock_update.message.message_id = 43
    mock_update.message.text = "/restart"
    mock_update.message.reply_text = AsyncMock()

    await connector._handle_telegram_message(mock_update, MagicMock())

    mock_handler.assert_not_called()
    mock_update.message.reply_text.assert_called_once()
    assert "Access denied" in mock_update.message.reply_text.call_args[0][0]


@pytest.mark.asyncio
async def test_telegram_connector_channel_post_authorization():
    connector = TelegramConnector(
        bot_token="fake:token",
        allowed_user_ids=set(),
        allowed_chat_ids={"-1001234567890"},
        default_chat_id="-1001234567890",
    )
    assert connector.is_chat_authorized("-1001234567890") is True
    assert connector.is_chat_authorized(-1001234567890) is True
    assert connector.is_chat_authorized("-1009999999999") is False
    assert connector.is_chat_authorized(None) is False

    received_msgs: list[IncomingMessage] = []

    async def handler(msg: IncomingMessage) -> str:
        received_msgs.append(msg)
        return "Channel response"

    connector.register_message_handler(handler)

    # Simulate channel post (effective_user is None)
    mock_update = MagicMock()
    mock_update.message = None
    mock_update.effective_user = None
    mock_update.effective_chat.id = -1001234567890
    mock_update.effective_chat.username = "ops_channel"
    mock_update.effective_chat.title = "Homelab Ops"
    mock_update.effective_chat.type = "channel"
    mock_update.effective_message.message_id = 101
    mock_update.effective_message.message_thread_id = None
    mock_update.effective_message.text = "Check k8s status"
    mock_update.effective_message.reply_text = AsyncMock()

    await connector._handle_telegram_message(mock_update, MagicMock())

    assert len(received_msgs) == 1
    assert received_msgs[0].text == "Check k8s status"
    assert received_msgs[0].chat_id == "-1001234567890"
    assert received_msgs[0].user.user_id == "-1001234567890"
    mock_update.effective_message.reply_text.assert_called_once_with(
        "Channel response",
        parse_mode="HTML",
        reply_to_message_id=101,
        message_thread_id=None,
        allow_sending_without_reply=True,
    )


@pytest.mark.asyncio
async def test_telegram_connector_unauthorized_channel_post():
    connector = TelegramConnector(
        bot_token="fake:token",
        allowed_user_ids=set(),
        allowed_chat_ids={"-1001234567890"},
    )
    mock_handler = AsyncMock()
    connector.register_message_handler(mock_handler)

    # Channel not in allowed list
    mock_update = MagicMock()
    mock_update.effective_user = None
    mock_update.effective_chat.id = -1009999999999
    mock_update.effective_chat.type = "channel"
    mock_update.effective_message.message_id = 102
    mock_update.effective_message.text = "Unauthorized message"
    mock_update.effective_message.reply_text = AsyncMock()

    await connector._handle_telegram_message(mock_update, MagicMock())

    mock_handler.assert_not_called()
    mock_update.effective_message.reply_text.assert_not_called()


@pytest.mark.asyncio
async def test_telegram_connector_automatic_forward_ignored():
    """Verify automatic channel forwards into the discussion group do not trigger handlers."""
    connector = TelegramConnector(
        bot_token="fake:token",
        allowed_chat_ids={"-1004400196957"},
        discussion_group_id="-1004400196957",
    )
    handler = AsyncMock()
    connector.register_message_handler(handler)

    mock_update = MagicMock()
    mock_update.message = None
    mock_update.effective_chat.id = -1004400196957
    mock_update.effective_message.text = "Forwarded text"
    mock_update.effective_message.is_automatic_forward = True

    await connector._handle_telegram_message(mock_update, MagicMock())
    handler.assert_not_called()
