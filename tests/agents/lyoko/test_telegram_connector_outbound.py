from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from lyoko.application.chat_manager import ChatManager
from lyoko.domain.models.chat import (
    ApprovalAction,
    ApprovalRequest,
)
from lyoko.infrastructure.chat.telegram import TelegramConnector


@pytest.mark.asyncio
async def test_telegram_connector_send_message():
    connector = TelegramConnector(
        bot_token="fake:token", allowed_user_ids={"12345"}, default_chat_id="default_chat"
    )
    # When app is not initialized
    await connector.send_message("12345", "Test")

    mock_app = MagicMock()
    mock_app.bot.send_message = AsyncMock()
    connector._app = mock_app

    # Explicit chat_id
    await connector.send_message("12345", "Hello")
    mock_app.bot.send_message.assert_called_once_with(
        chat_id="12345",
        text="Hello",
        parse_mode="HTML",
        reply_to_message_id=None,
        message_thread_id=None,
        allow_sending_without_reply=True,
    )

    # Default chat_id fallback
    mock_app.bot.send_message.reset_mock()
    await connector.send_message("", "Broadcast")
    mock_app.bot.send_message.assert_called_once_with(
        chat_id="default_chat",
        text="Broadcast",
        parse_mode="HTML",
        reply_to_message_id=None,
        message_thread_id=None,
        allow_sending_without_reply=True,
    )

    # With reply_to_message_id
    mock_app.bot.send_message.reset_mock()
    await connector.send_message("12345", "Reply text", reply_to_message_id="42")
    mock_app.bot.send_message.assert_called_once_with(
        chat_id="12345",
        text="Reply text",
        parse_mode="HTML",
        reply_to_message_id=42,
        message_thread_id=None,
        allow_sending_without_reply=True,
    )


@pytest.mark.asyncio
async def test_telegram_connector_send_approval_request():
    connector = TelegramConnector(
        bot_token="fake:token", allowed_user_ids={"12345"}, default_chat_id="default_chat"
    )
    mock_app = MagicMock()
    mock_app.bot.send_message = AsyncMock()
    connector._app = mock_app

    req = ApprovalRequest(
        incident_id="inc-99",
        title="OOMKilled detected",
        details="Bump memory from 256Mi to 512Mi",
        chat_id="target_chat",
        actions=[
            ApprovalAction(action_id="approve", label="Approve Bump", style="primary"),
            ApprovalAction(action_id="reject", label="Reject", style="danger"),
        ],
    )

    await connector.send_approval_request(req)

    mock_app.bot.send_message.assert_called_once()
    call_kwargs = mock_app.bot.send_message.call_args[1]
    assert call_kwargs["chat_id"] == "target_chat"
    assert "OOMKilled detected" in call_kwargs["text"]
    assert "Bump memory from 256Mi to 512Mi" in call_kwargs["text"]
    keyboard = call_kwargs["reply_markup"]
    assert keyboard is not None
    assert len(keyboard.inline_keyboard[0]) == 2
    assert keyboard.inline_keyboard[0][0].callback_data == "approve:inc-99"
    assert keyboard.inline_keyboard[0][1].callback_data == "reject:inc-99"


@pytest.mark.asyncio
async def test_telegram_connector_lifecycle():
    connector = TelegramConnector(bot_token="", allowed_user_ids=set())
    # Should safely return without token
    await connector.start()
    assert connector._app is None

    connector = TelegramConnector(bot_token="123456:fake_token", allowed_user_ids={"123"})
    with patch("lyoko.infrastructure.chat.telegram.Application") as mock_app_class:
        mock_builder = MagicMock()
        mock_app_class.builder.return_value = mock_builder
        mock_builder.token.return_value = mock_builder
        mock_builder.concurrent_updates.return_value = mock_builder
        mock_app = MagicMock()
        mock_builder.build.return_value = mock_app
        mock_app.initialize = AsyncMock()
        mock_app.start = AsyncMock()
        mock_app.updater.start_polling = AsyncMock()
        mock_app.updater.stop = AsyncMock()
        mock_app.updater.running = True
        mock_app.stop = AsyncMock()
        mock_app.shutdown = AsyncMock()

        await connector.start()
        # A handler waiting for an approval must not block the button click that grants it.
        mock_builder.concurrent_updates.assert_called_once_with(True)
        mock_app.initialize.assert_called_once()
        mock_app.start.assert_called_once()
        mock_app.updater.start_polling.assert_called_once()

        await connector.stop()
        mock_app.updater.stop.assert_called_once()
        mock_app.stop.assert_called_once()
        mock_app.shutdown.assert_called_once()


@pytest.mark.asyncio
async def test_chat_manager():
    conn1 = AsyncMock()
    conn2 = AsyncMock()

    manager = ChatManager([conn1, conn2])
    assert len(manager.connectors) == 2

    conn3 = AsyncMock()
    manager.add_connector(conn3)
    assert len(manager.connectors) == 3

    await manager.start_all()
    conn1.start.assert_called_once()
    conn2.start.assert_called_once()
    conn3.start.assert_called_once()

    await manager.stop_all()
    conn1.stop.assert_called_once()
    conn2.stop.assert_called_once()
    conn3.stop.assert_called_once()

    # Broadcast message
    await manager.broadcast_message("chat_123", "Alert text")
    conn1.send_message.assert_called_once_with(
        chat_id="chat_123",
        text="Alert text",
        reply_to_message_id=None,
        parse_mode="Markdown",
        message_thread_id=None,
    )
    conn2.send_message.assert_called_once_with(
        chat_id="chat_123",
        text="Alert text",
        reply_to_message_id=None,
        parse_mode="Markdown",
        message_thread_id=None,
    )
    conn3.send_message.assert_called_once_with(
        chat_id="chat_123",
        text="Alert text",
        reply_to_message_id=None,
        parse_mode="Markdown",
        message_thread_id=None,
    )

    # Broadcast approval request
    req = ApprovalRequest(
        incident_id="inc-1",
        title="Test",
        details="Details",
        chat_id="123",
    )
    await manager.broadcast_approval_request(req)
    conn1.send_approval_request.assert_called_once_with(
        req, message_thread_id=None, reply_to_message_id=None
    )
    conn2.send_approval_request.assert_called_once_with(
        req, message_thread_id=None, reply_to_message_id=None
    )
    conn3.send_approval_request.assert_called_once_with(
        req, message_thread_id=None, reply_to_message_id=None
    )

    # Fault tolerance: one connector raises
    conn1.send_message.side_effect = RuntimeError("Network error")
    conn2.send_message.reset_mock()
    await manager.broadcast_message("chat_123", "Alert text 2")
    conn2.send_message.assert_called_once_with(
        chat_id="chat_123",
        text="Alert text 2",
        reply_to_message_id=None,
        parse_mode="Markdown",
        message_thread_id=None,
    )


@pytest.mark.asyncio
async def test_telegram_connector_edit_message_success():
    """Verify edit_message successfully updates message in Telegram."""
    connector = TelegramConnector(
        bot_token="fake:token", allowed_user_ids={"12345"}, default_chat_id="12345"
    )
    mock_app = MagicMock()
    mock_sent_msg = MagicMock()
    mock_sent_msg.message_id = 999
    mock_sent_msg.chat_id = 12345
    mock_app.bot.edit_message_text = AsyncMock(return_value=mock_sent_msg)
    connector._app = mock_app

    res = await connector.edit_message(
        chat_id="12345",
        message_id="999",
        text="**Updated** status",
        parse_mode="HTML",
    )

    assert res is not None
    assert res.message_id == "999"
    assert res.chat_id == "12345"
    mock_app.bot.edit_message_text.assert_called_once_with(
        chat_id="12345",
        message_id=999,
        text="<b>Updated</b> status",
        parse_mode="HTML",
    )


@pytest.mark.asyncio
async def test_chat_manager_edit_message_and_broadcast_message():
    """Verify ChatManager routes edit_message and broadcast_message returning SentMessage."""
    connector = TelegramConnector(
        bot_token="fake:token", allowed_user_ids={"12345"}, default_chat_id="12345"
    )
    mock_app = MagicMock()
    mock_sent_msg = MagicMock()
    mock_sent_msg.message_id = 100
    mock_sent_msg.chat_id = 12345
    mock_app.bot.send_message = AsyncMock(return_value=mock_sent_msg)
    mock_app.bot.edit_message_text = AsyncMock(return_value=mock_sent_msg)
    connector._app = mock_app

    manager = ChatManager(connectors=[connector])

    # Broadcast message
    sent_list = await manager.broadcast_message(chat_id="12345", text="Initial alert")
    assert len(sent_list) == 1
    assert sent_list[0].message_id == "100"

    # Edit message
    edited_list = await manager.edit_message(
        chat_id="12345", message_id="100", text="Edited status"
    )
    assert len(edited_list) == 1
    assert edited_list[0].message_id == "100"
