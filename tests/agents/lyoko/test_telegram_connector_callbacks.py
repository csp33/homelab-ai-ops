from unittest.mock import AsyncMock, MagicMock

import pytest
from lyoko.domain.models.chat import (
    ApprovalResponse,
)
from lyoko.infrastructure.chat.telegram import TelegramConnector


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

    assert "Rejected" in mock_query.edit_message_text.call_args[0][0]


@pytest.mark.asyncio
async def test_telegram_connector_callback_query_force():
    connector = TelegramConnector(
        bot_token="fake:token", allowed_user_ids={"12345"}, default_chat_id="12345"
    )
    received_approvals: list[ApprovalResponse] = []

    async def approval_handler(resp: ApprovalResponse) -> None:
        received_approvals.append(resp)

    connector.register_approval_handler(approval_handler)

    mock_update = MagicMock()
    mock_update.effective_user.id = 12345
    mock_update.effective_user.first_name = "Admin"
    mock_query = MagicMock()
    mock_query.data = "force:inc-abc"
    mock_query.message.text = "Alert suppressed in cooldown"
    mock_query.answer = AsyncMock()
    mock_query.edit_message_text = AsyncMock()
    mock_update.callback_query = mock_query

    await connector._handle_callback_query(mock_update, MagicMock())

    mock_query.answer.assert_called_once()
    assert len(received_approvals) == 1
    assert received_approvals[0].incident_id == "inc-abc"
    assert received_approvals[0].approved is True
    assert received_approvals[0].action_id == "force"
    mock_query.edit_message_text.assert_called_once()
    assert "Investigation forced" in mock_query.edit_message_text.call_args[0][0]


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
async def test_telegram_connector_feedback_callback_button():
    """Verify clicking feedback/teach button sets redirection mode."""
    connector = TelegramConnector(
        bot_token="fake:token", allowed_user_ids={"12345"}, default_chat_id="12345"
    )
    mock_approval_handler = AsyncMock()
    connector.register_approval_handler(mock_approval_handler)

    mock_update = MagicMock()
    mock_update.effective_user.id = 12345
    mock_update.effective_user.first_name = "Admin"
    mock_update.effective_chat.id = 12345
    mock_update.callback_query.data = "feedback:incident-influxdb-0"
    mock_update.callback_query.answer = AsyncMock()
    mock_update.callback_query.edit_message_text = AsyncMock()
    mock_update.callback_query.message.text = "Remediation approval required"

    await connector._handle_callback_query(mock_update, MagicMock())

    assert mock_approval_handler.called
    resp: ApprovalResponse = mock_approval_handler.call_args[0][0]
    assert resp.incident_id == "incident-influxdb-0"
    assert resp.approved is False
    assert resp.action_id == "feedback"
    assert "redirection" in resp.reason.lower()
    assert mock_update.callback_query.edit_message_text.called
    edited_text = mock_update.callback_query.edit_message_text.call_args[0][0]
    assert "Teaching mode activated" in edited_text


@pytest.mark.asyncio
async def test_telegram_connector_stop_callback():
    """Verify clicking Stop aborts the in-flight streaming reply and clears the button."""
    connector = TelegramConnector(
        bot_token="fake:token", allowed_user_ids={"12345"}, default_chat_id="12345"
    )
    streamer = MagicMock()
    connector._active_streamers[("12345", 555)] = streamer

    mock_update = MagicMock()
    mock_update.effective_user.id = 12345
    mock_update.effective_chat.id = 12345
    mock_query = MagicMock()
    mock_query.data = "stop:555"
    mock_query.answer = AsyncMock()
    mock_query.edit_message_reply_markup = AsyncMock()
    mock_update.callback_query = mock_query

    await connector._handle_callback_query(mock_update, MagicMock())

    streamer.stop.assert_called_once()
    mock_query.edit_message_reply_markup.assert_called_once_with(reply_markup=None)


@pytest.mark.asyncio
async def test_telegram_connector_feedback_command():
    """Verify /feedback command saves rule to PostgreSQL and generates embedding."""
    mock_memory_repo = AsyncMock()
    mock_memory_repo.save_memory.return_value = 77

    mock_embeddings = AsyncMock()
    mock_embeddings.embed_text.return_value = [0.05] * 1536

    connector = TelegramConnector(
        bot_token="fake:token",
        allowed_user_ids={"12345"},
        default_chat_id="12345",
        memory_repository=mock_memory_repo,
        embeddings_service=mock_embeddings,
    )

    mock_update = MagicMock()
    mock_update.effective_user.id = 12345
    mock_update.effective_chat.id = 12345
    mock_update.message.message_id = 88
    mock_update.message.text = "/feedback For influxdb, compact WAL logs before restart"
    mock_update.message.reply_to_message.text = (
        "Pod: influxdb-0\nNamespace: monitoring\nAlert: PodCrashLooping"
    )
    mock_update.message.reply_text = AsyncMock()

    await connector._handle_telegram_message(mock_update, MagicMock())

    assert mock_memory_repo.save_memory.called
    entry = mock_memory_repo.save_memory.call_args[0][0]
    assert entry.namespace == "monitoring"
    assert entry.service_name == "influxdb"
    assert entry.operator_feedback == "For influxdb, compact WAL logs before restart"
    assert mock_embeddings.embed_text.called

    assert mock_update.message.reply_text.called
    reply_msg = mock_update.message.reply_text.call_args[0][0]
    assert "Rule learned" in reply_msg
    assert "77" in reply_msg
