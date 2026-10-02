from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from homelab_mcp.domain.interfaces.telegram import TelegramClientInterface
from homelab_mcp.domain.models.telegram import (
    TelegramAlertRequest,
    TelegramMessageRequest,
    TelegramSeverity,
)
from homelab_mcp.infrastructure.telegram.client import TelegramClient
from pydantic import SecretStr


@pytest.mark.asyncio
async def test_telegram_client_send_message_success():
    client = TelegramClient(bot_token="fake_token", default_chat_id="12345")
    assert isinstance(client, TelegramClientInterface)
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"ok": True, "result": {"message_id": 100}}

    with patch(
        "httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response
    ) as mock_post:
        result = await client.send_message(
            TelegramMessageRequest(text="Hello Homelab", chat_id="12345")
        )
        assert result["ok"] is True
        assert result["result"]["message_id"] == 100
        mock_post.assert_called_once()
        assert "sendMessage" in mock_post.call_args[0][0]
        assert mock_post.call_args[1]["json"] == {
            "chat_id": "12345",
            "text": "Hello Homelab",
            "parse_mode": "Markdown",
        }


@pytest.mark.asyncio
async def test_telegram_client_send_message_with_secret_str_and_default_chat_id():
    client = TelegramClient(bot_token=SecretStr("secret_token"), default_chat_id="99999")
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"ok": True, "result": {"message_id": 102}}

    with patch(
        "httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response
    ) as mock_post:
        result = await client.send_message(TelegramMessageRequest(text="Using default chat"))
        assert result["ok"] is True
        assert client.base_url == "https://api.telegram.org/botsecret_token"
        assert mock_post.call_args[1]["json"]["chat_id"] == "99999"


@pytest.mark.asyncio
async def test_telegram_client_send_alert_formatting():
    client = TelegramClient(bot_token="fake_token", default_chat_id="12345")
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"ok": True, "result": {"message_id": 101}}

    with patch(
        "httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response
    ) as mock_post:
        req = TelegramAlertRequest(
            title="Pod Crash", message="Pod foo in crashloop", severity=TelegramSeverity.CRITICAL
        )
        result = await client.send_alert(req)
        assert result["ok"] is True
        payload = mock_post.call_args[1]["json"]
        assert "🚨" in payload["text"]
        assert "Pod Crash" in payload["text"]
        assert "Pod foo in crashloop" in payload["text"]
        assert payload["chat_id"] == "12345"


@pytest.mark.asyncio
async def test_telegram_client_send_alert_severities():
    client = TelegramClient(bot_token="fake_token", default_chat_id="12345")
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"ok": True, "result": {"message_id": 103}}

    severities = [
        (TelegramSeverity.INFO, "ℹ️"),
        (TelegramSeverity.WARNING, "⚠️"),
        (TelegramSeverity.CRITICAL, "🚨"),
        (TelegramSeverity.OK, "✅"),
    ]

    for severity, icon in severities:
        with patch(
            "httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response
        ) as mock_post:
            req = TelegramAlertRequest(title="Status", message="Details", severity=severity)
            await client.send_alert(req)
            payload = mock_post.call_args[1]["json"]
            assert icon in payload["text"]
            assert f"[{severity.value.upper()}]" in payload["text"]


@pytest.mark.asyncio
async def test_telegram_client_missing_chat_id_raises_value_error():
    client = TelegramClient(bot_token="fake_token", default_chat_id=None)
    with pytest.raises(ValueError, match="No chat_id specified and no default_chat_id configured"):
        await client.send_message(TelegramMessageRequest(text="Hello", chat_id=None))


@pytest.mark.asyncio
async def test_telegram_client_missing_token_raises_value_error():
    client = TelegramClient(bot_token=None, default_chat_id="12345")
    with pytest.raises(ValueError, match="Telegram bot token not configured"):
        await client.send_message(TelegramMessageRequest(text="Hello", chat_id="12345"))


@pytest.mark.asyncio
async def test_telegram_client_http_error_raised():
    client = TelegramClient(bot_token="fake_token", default_chat_id="12345")
    mock_response = httpx.Response(400, request=httpx.Request("POST", "https://api.telegram.org"))

    with (
        patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response),
        pytest.raises(httpx.HTTPStatusError),
    ):
        await client.send_message(TelegramMessageRequest(text="Hello"))
