"""Tests for Telegram memory management commands (/forget, /memories)."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from lyoko.domain.models.memory import MemoryEntry
from lyoko.infrastructure.chat.telegram import TelegramConnector


@pytest.mark.asyncio
async def test_telegram_connector_forget_command_success():
    """Verify /forget <id> deletes memory from database and sends success message."""
    mock_memory_repo = AsyncMock()
    mock_memory_repo.delete_memory.return_value = True

    connector = TelegramConnector(
        bot_token="fake:token",
        allowed_user_ids={"12345"},
        default_chat_id="12345",
        memory_repository=mock_memory_repo,
    )

    mock_update = MagicMock()
    mock_update.effective_user.id = 12345
    mock_update.effective_chat.id = 12345
    mock_update.message.message_id = 88
    mock_update.message.text = "/forget 42"
    mock_update.message.reply_text = AsyncMock()

    await connector._handle_telegram_message(mock_update, MagicMock())

    mock_memory_repo.delete_memory.assert_called_once_with(42)
    assert mock_update.message.reply_text.called
    reply_msg = mock_update.message.reply_text.call_args[0][0]
    assert "deleted successfully" in reply_msg
    assert "42" in reply_msg


@pytest.mark.asyncio
async def test_telegram_connector_forget_command_not_found():
    """Verify /forget <id> notifies operator when memory ID does not exist."""
    mock_memory_repo = AsyncMock()
    mock_memory_repo.delete_memory.return_value = False

    connector = TelegramConnector(
        bot_token="fake:token",
        allowed_user_ids={"12345"},
        default_chat_id="12345",
        memory_repository=mock_memory_repo,
    )

    mock_update = MagicMock()
    mock_update.effective_user.id = 12345
    mock_update.effective_chat.id = 12345
    mock_update.message.message_id = 89
    mock_update.message.text = "/forget 999"
    mock_update.message.reply_text = AsyncMock()

    await connector._handle_telegram_message(mock_update, MagicMock())

    mock_memory_repo.delete_memory.assert_called_once_with(999)
    assert mock_update.message.reply_text.called
    reply_msg = mock_update.message.reply_text.call_args[0][0]
    assert "not found" in reply_msg
    assert "999" in reply_msg


@pytest.mark.asyncio
async def test_telegram_connector_forget_command_invalid_argument():
    """Verify /forget with invalid argument displays usage instructions."""
    mock_memory_repo = AsyncMock()

    connector = TelegramConnector(
        bot_token="fake:token",
        allowed_user_ids={"12345"},
        default_chat_id="12345",
        memory_repository=mock_memory_repo,
    )

    mock_update = MagicMock()
    mock_update.effective_user.id = 12345
    mock_update.effective_chat.id = 12345
    mock_update.message.message_id = 90
    mock_update.message.text = "/forget not_a_number"
    mock_update.message.reply_text = AsyncMock()

    await connector._handle_telegram_message(mock_update, MagicMock())

    mock_memory_repo.delete_memory.assert_not_called()
    assert mock_update.message.reply_text.called
    reply_msg = mock_update.message.reply_text.call_args[0][0]
    assert "Forget usage" in reply_msg or "Invalid memory ID" in reply_msg


@pytest.mark.asyncio
async def test_telegram_connector_forget_command_no_args_lists_memories():
    """Verify /forget without arguments shows usage and lists recent memories."""
    mock_memory_repo = AsyncMock()
    mock_memory_repo.list_recent_memories.return_value = [
        MemoryEntry(
            id=15,
            namespace="monitoring",
            service_name="influxdb",
            alert_name="OOM",
            incident_pattern="OOMKilled",
            operator_feedback="Do not increase RAM",
            action_rule="Compact logs first",
            created_at=datetime.now(UTC),
        )
    ]

    connector = TelegramConnector(
        bot_token="fake:token",
        allowed_user_ids={"12345"},
        default_chat_id="12345",
        memory_repository=mock_memory_repo,
    )

    mock_update = MagicMock()
    mock_update.effective_user.id = 12345
    mock_update.effective_chat.id = 12345
    mock_update.message.message_id = 91
    mock_update.message.text = "/forget"
    mock_update.message.reply_text = AsyncMock()

    await connector._handle_telegram_message(mock_update, MagicMock())

    mock_memory_repo.delete_memory.assert_not_called()
    mock_memory_repo.list_recent_memories.assert_called_once()
    assert mock_update.message.reply_text.called
    reply_msg = mock_update.message.reply_text.call_args[0][0]
    assert "Forget usage" in reply_msg
    assert "15" in reply_msg
    assert "influxdb" in reply_msg


@pytest.mark.asyncio
async def test_telegram_connector_forget_command_no_db():
    """Verify /forget returns error message when memory repository is not configured."""
    connector = TelegramConnector(
        bot_token="fake:token",
        allowed_user_ids={"12345"},
        default_chat_id="12345",
        memory_repository=None,
    )

    mock_update = MagicMock()
    mock_update.effective_user.id = 12345
    mock_update.effective_chat.id = 12345
    mock_update.message.message_id = 92
    mock_update.message.text = "/forget 42"
    mock_update.message.reply_text = AsyncMock()

    await connector._handle_telegram_message(mock_update, MagicMock())

    assert mock_update.message.reply_text.called
    reply_msg = mock_update.message.reply_text.call_args[0][0]
    assert "database" in reply_msg
    assert "not available" in reply_msg


@pytest.mark.asyncio
async def test_telegram_connector_memories_command():
    """Verify /memories lists stored memories with IDs and formatted details."""
    mock_memory_repo = AsyncMock()
    mock_memory_repo.list_recent_memories.return_value = [
        MemoryEntry(
            id=10,
            namespace="default",
            service_name="frontend",
            alert_name=None,
            incident_pattern="CrashLoop",
            operator_feedback="Check DNS",
            action_rule="Check DNS",
            created_at=datetime.now(UTC),
        )
    ]

    connector = TelegramConnector(
        bot_token="fake:token",
        allowed_user_ids={"12345"},
        default_chat_id="12345",
        memory_repository=mock_memory_repo,
    )

    mock_update = MagicMock()
    mock_update.effective_user.id = 12345
    mock_update.effective_chat.id = 12345
    mock_update.message.message_id = 93
    mock_update.message.text = "/memories"
    mock_update.message.reply_text = AsyncMock()

    await connector._handle_telegram_message(mock_update, MagicMock())

    mock_memory_repo.list_recent_memories.assert_called_once()
    assert mock_update.message.reply_text.called
    reply_msg = mock_update.message.reply_text.call_args[0][0]
    assert "10" in reply_msg
    assert "frontend" in reply_msg
    assert "Check DNS" in reply_msg
    assert "/forget" in reply_msg


@pytest.mark.asyncio
async def test_telegram_connector_memories_command_empty():
    """Verify /memories indicates when no memories are stored."""
    mock_memory_repo = AsyncMock()
    mock_memory_repo.list_recent_memories.return_value = []

    connector = TelegramConnector(
        bot_token="fake:token",
        allowed_user_ids={"12345"},
        default_chat_id="12345",
        memory_repository=mock_memory_repo,
    )

    mock_update = MagicMock()
    mock_update.effective_user.id = 12345
    mock_update.effective_chat.id = 12345
    mock_update.message.message_id = 94
    mock_update.message.text = "/memories"
    mock_update.message.reply_text = AsyncMock()

    await connector._handle_telegram_message(mock_update, MagicMock())

    assert mock_update.message.reply_text.called
    reply_msg = mock_update.message.reply_text.call_args[0][0]
    assert "No memories found" in reply_msg
