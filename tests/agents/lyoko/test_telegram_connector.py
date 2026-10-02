from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from lyoko.domain.models.chat import (
    ApprovalAction,
    ApprovalRequest,
    ApprovalResponse,
    IncomingMessage,
)
from lyoko.infrastructure.chat.manager import ChatManager
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
    mock_update.message.text = "/status"
    mock_update.message.reply_text = AsyncMock()

    await connector._handle_telegram_message(mock_update, MagicMock())

    assert len(received_msgs) == 1
    assert received_msgs[0].text == "/status"
    assert received_msgs[0].user.user_id == "12345"
    assert received_msgs[0].user.username == "admin"
    mock_update.message.reply_text.assert_called_once_with("Acknowledged", parse_mode="HTML")


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
async def test_telegram_connector_callback_query_approval():
    connector = TelegramConnector(
        bot_token="fake:token", allowed_user_ids={"12345"}, default_chat_id="12345"
    )
    received_approvals: list[ApprovalResponse] = []

    async def approval_handler(resp: ApprovalResponse) -> None:
        received_approvals.append(resp)

    connector.register_approval_handler(approval_handler)

    mock_update = MagicMock()
    mock_update.effective_user.id = 12345
    mock_query = MagicMock()
    mock_query.data = "approve:inc-abc"
    mock_query.message.text = "Approval prompt"
    mock_query.answer = AsyncMock()
    mock_query.edit_message_text = AsyncMock()
    mock_update.callback_query = mock_query

    await connector._handle_callback_query(mock_update, MagicMock())

    mock_query.answer.assert_called_once()
    assert len(received_approvals) == 1
    assert received_approvals[0].incident_id == "inc-abc"
    assert received_approvals[0].approved is True
    assert received_approvals[0].user_id == "12345"
    assert received_approvals[0].action_id == "approve"
    mock_query.edit_message_text.assert_called_once()
    assert "Approved" in mock_query.edit_message_text.call_args[0][0]


@pytest.mark.asyncio
async def test_telegram_connector_callback_query_rejection():
    connector = TelegramConnector(
        bot_token="fake:token", allowed_user_ids={"12345"}, default_chat_id="12345"
    )
    received_approvals: list[ApprovalResponse] = []

    async def approval_handler(resp: ApprovalResponse) -> None:
        received_approvals.append(resp)

    connector.register_approval_handler(approval_handler)

    mock_update = MagicMock()
    mock_update.effective_user.id = 12345
    mock_query = MagicMock()
    mock_query.data = "reject:inc-abc"
    mock_query.message.text = "Approval prompt"
    mock_query.answer = AsyncMock()
    mock_query.edit_message_text = AsyncMock()
    mock_update.callback_query = mock_query

    await connector._handle_callback_query(mock_update, MagicMock())

    assert len(received_approvals) == 1
    assert received_approvals[0].incident_id == "inc-abc"
    assert received_approvals[0].approved is False
    assert "Rejected" in mock_query.edit_message_text.call_args[0][0]


@pytest.mark.asyncio
async def test_telegram_connector_callback_query_unauthorized():
    connector = TelegramConnector(
        bot_token="fake:token", allowed_user_ids={"12345"}, default_chat_id="12345"
    )
    mock_handler = AsyncMock()
    connector.register_approval_handler(mock_handler)

    mock_update = MagicMock()
    mock_update.effective_user.id = 99999
    mock_query = MagicMock()
    mock_query.data = "approve:inc-abc"
    mock_query.answer = AsyncMock()
    mock_update.callback_query = mock_query

    await connector._handle_callback_query(mock_update, MagicMock())

    mock_query.answer.assert_called_once_with("⛔ Unauthorized", show_alert=True)
    mock_handler.assert_not_called()


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
        chat_id="12345", text="Hello", parse_mode="HTML"
    )

    # Default chat_id fallback
    mock_app.bot.send_message.reset_mock()
    await connector.send_message("", "Broadcast")
    mock_app.bot.send_message.assert_called_once_with(
        chat_id="default_chat", text="Broadcast", parse_mode="HTML"
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
        chat_id="chat_123", text="Alert text", parse_mode="Markdown"
    )
    conn2.send_message.assert_called_once_with(
        chat_id="chat_123", text="Alert text", parse_mode="Markdown"
    )
    conn3.send_message.assert_called_once_with(
        chat_id="chat_123", text="Alert text", parse_mode="Markdown"
    )

    # Broadcast approval request
    req = ApprovalRequest(
        incident_id="inc-1",
        title="Test",
        details="Details",
        chat_id="123",
    )
    await manager.broadcast_approval_request(req)
    conn1.send_approval_request.assert_called_once_with(req)
    conn2.send_approval_request.assert_called_once_with(req)
    conn3.send_approval_request.assert_called_once_with(req)

    # Fault tolerance: one connector raises
    conn1.send_message.side_effect = RuntimeError("Network error")
    conn2.send_message.reset_mock()
    await manager.broadcast_message("chat_123", "Alert text 2")
    conn2.send_message.assert_called_once_with(
        chat_id="chat_123", text="Alert text 2", parse_mode="Markdown"
    )


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
    mock_update.effective_message.text = "Check k8s status"
    mock_update.effective_message.reply_text = AsyncMock()

    await connector._handle_telegram_message(mock_update, MagicMock())

    assert len(received_msgs) == 1
    assert received_msgs[0].text == "Check k8s status"
    assert received_msgs[0].chat_id == "-1001234567890"
    assert received_msgs[0].user.user_id == "-1001234567890"
    mock_update.effective_message.reply_text.assert_called_once_with(
        "Channel response", parse_mode="HTML"
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


def test_markdown_to_telegram_html():
    from lyoko.infrastructure.chat.telegram import markdown_to_telegram_html

    # Empty / none
    assert markdown_to_telegram_html("") == ""

    # Bold and italics
    assert markdown_to_telegram_html("**bold text**") == "<b>bold text</b>"
    assert markdown_to_telegram_html("*italic text*") == "<i>italic text</i>"

    # Underscores in identifiers must NOT be eaten or converted to italic
    assert (
        markdown_to_telegram_html("Connected to MOVISTAR_25EO_IOT wifi network")
        == "Connected to MOVISTAR_25EO_IOT wifi network"
    )

    # Inline code
    assert (
        markdown_to_telegram_html("Use `kubectl get pods -n kube-system` now")
        == "Use <code>kubectl get pods -n kube-system</code> now"
    )

    # Code block with language
    code_block = '```json\n{"status": "ok"}\n```'
    assert (
        markdown_to_telegram_html(code_block)
        == '<pre><code class="language-json">{\n  &quot;status&quot;: &quot;ok&quot;\n}\n</code></pre>'
        or "<pre><code>" in markdown_to_telegram_html(code_block)
    )

    # HTML special characters escaping
    assert markdown_to_telegram_html("5 < 10 && 10 > 5") == "5 &lt; 10 &amp;&amp; 10 &gt; 5"

    # Headers
    assert markdown_to_telegram_html("### Header Title") == "<b>Header Title</b>"

    # Links
    assert (
        markdown_to_telegram_html("[Grafana](http://grafana.local)")
        == '<a href="http://grafana.local">Grafana</a>'
    )
