import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from lyoko.domain.models.chat import (
    IncomingMessage,
)
from lyoko.infrastructure.chat.telegram import TelegramConnector


@pytest.mark.asyncio
async def test_telegram_draft_streamer_thinking_and_tokens():
    """Verify TelegramDraftStreamer sends thinking draft and throttled token updates."""
    from lyoko.infrastructure.chat.streamer import TelegramDraftStreamer

    mock_bot = MagicMock()
    mock_bot.send_message_draft = AsyncMock()

    streamer = TelegramDraftStreamer(
        bot=mock_bot,
        chat_id="12345",
        chat_type="private",
        draft_id=999,
        min_interval_seconds=0.0,  # no delay in test
    )

    await streamer.start_thinking()
    mock_bot.send_message_draft.assert_called_once_with(
        chat_id=12345,
        draft_id=999,
        text="",
        api_kwargs={"can_stop": True},
    )

    mock_bot.send_message_draft.reset_mock()
    await streamer.on_token("Hello ")
    await streamer.on_token("world!")

    assert mock_bot.send_message_draft.call_count >= 1
    last_call = mock_bot.send_message_draft.call_args[1]
    assert last_call["text"] == "Hello world!"
    assert last_call["draft_id"] == 999
    assert last_call["api_kwargs"] == {"can_stop": True}


@pytest.mark.asyncio
async def test_telegram_draft_streamer_stop():
    """Verify stop() marks streamer stopped and on_token raises CancelledError."""
    from lyoko.infrastructure.chat.streamer import TelegramDraftStreamer

    mock_bot = MagicMock()
    mock_bot.send_message_draft = AsyncMock()

    streamer = TelegramDraftStreamer(
        bot=mock_bot, chat_id="12345", chat_type="private", draft_id=123
    )
    assert streamer.is_stopped() is False

    streamer.stop()
    assert streamer.is_stopped() is True

    with pytest.raises(asyncio.CancelledError):
        await streamer.on_token("token after stop")


@pytest.mark.asyncio
async def test_telegram_connector_handle_stopped_generation():
    """Verify _handle_stopped_generation cancels active streamer."""
    from lyoko.infrastructure.chat.streamer import TelegramDraftStreamer

    connector = TelegramConnector(
        bot_token="fake:token", allowed_user_ids={"12345"}, default_chat_id="12345"
    )
    streamer = TelegramDraftStreamer(
        bot=MagicMock(), chat_id="12345", chat_type="private", draft_id=777
    )
    connector._active_streamers[("12345", 777)] = streamer

    mock_update = MagicMock()
    mock_stopped = MagicMock()
    mock_stopped.chat.id = 12345
    mock_stopped.draft_id = 777
    mock_update.stopped_message_generation = mock_stopped

    await connector._handle_stopped_generation(mock_update, MagicMock())

    assert streamer.is_stopped() is True


@pytest.mark.asyncio
async def test_telegram_draft_streamer_graceful_failure():
    """Verify exceptions in send_message_draft disable streaming silently."""
    from lyoko.infrastructure.chat.streamer import TelegramDraftStreamer

    mock_bot = MagicMock()
    mock_bot.send_message_draft = AsyncMock(side_effect=RuntimeError("DRAFTS_NOT_SUPPORTED"))

    streamer = TelegramDraftStreamer(bot=mock_bot, chat_id="12345", chat_type="private")
    await streamer.start_thinking()
    assert streamer._disabled is True

    # Subsequent tokens should not call send_message_draft
    mock_bot.send_message_draft.reset_mock()
    await streamer.on_token("text")
    mock_bot.send_message_draft.assert_not_called()


@pytest.mark.asyncio
async def test_telegram_draft_streamer_skips_non_private_chat():
    """Verify streaming is disabled for groups/channels where send_message_draft cannot work."""
    from lyoko.infrastructure.chat.streamer import TelegramDraftStreamer

    mock_bot = MagicMock()
    mock_bot.send_message_draft = AsyncMock()

    streamer = TelegramDraftStreamer(bot=mock_bot, chat_id="-1001234567890", chat_type="supergroup")
    await streamer.start_thinking()
    await streamer.on_token("hello")

    assert streamer._disabled is True
    mock_bot.send_message_draft.assert_not_called()


@pytest.mark.asyncio
async def test_telegram_draft_streamer_retries_without_can_stop():
    """Verify a server that rejects can_stop still streams via a plain draft update."""
    from lyoko.infrastructure.chat.streamer import TelegramDraftStreamer

    mock_bot = MagicMock()
    mock_bot.send_message_draft = AsyncMock(
        side_effect=[
            RuntimeError("can_stop not supported"),
            None,
        ]
    )

    streamer = TelegramDraftStreamer(bot=mock_bot, chat_id="12345", chat_type="private")
    await streamer.start_thinking()

    assert streamer._disabled is False
    assert streamer._can_stop is False
    assert mock_bot.send_message_draft.call_count == 2
    assert mock_bot.send_message_draft.call_args_list[0].kwargs["api_kwargs"] == {"can_stop": True}
    assert "api_kwargs" not in mock_bot.send_message_draft.call_args_list[1].kwargs


@pytest.mark.asyncio
async def test_telegram_connector_handles_streaming_message_handler():
    """Verify _handle_telegram_message passes on_token callback to streaming handlers."""
    connector = TelegramConnector(
        bot_token="fake:token", allowed_user_ids={"12345"}, default_chat_id="12345"
    )

    streamed_tokens: list[str] = []

    async def streaming_handler(msg: IncomingMessage, on_token=None) -> str:
        if on_token:
            await on_token("Chunk 1 ")
            await on_token("Chunk 2")
            streamed_tokens.append("streamed")
        return "Final reply"

    connector.register_message_handler(streaming_handler)

    mock_bot = MagicMock()
    mock_bot.send_message_draft = AsyncMock()
    mock_context = MagicMock()
    mock_context.bot = mock_bot

    mock_update = MagicMock()
    mock_update.effective_user.id = 12345
    mock_update.effective_chat.id = 12345
    mock_update.effective_chat.type = "private"
    mock_update.message.message_id = 42
    mock_update.message.message_thread_id = None
    mock_update.message.text = "Hello stream"
    mock_update.message.set_reaction = AsyncMock()
    mock_update.message.reply_text = AsyncMock()

    await connector._handle_telegram_message(mock_update, mock_context)

    assert "streamed" in streamed_tokens
    mock_update.message.reply_text.assert_called_once_with(
        "Final reply",
        parse_mode="HTML",
        reply_to_message_id=42,
        message_thread_id=None,
        allow_sending_without_reply=True,
    )
    assert mock_bot.send_message_draft.call_count >= 1
