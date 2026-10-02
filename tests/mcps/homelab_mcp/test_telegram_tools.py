"""Tests for FastMCP Telegram tools integration."""

from unittest.mock import AsyncMock, patch

import pytest
from homelab_mcp.domain.interfaces.telegram import TelegramClientInterface
from homelab_mcp.domain.models.telegram import (
    TelegramAlertRequest,
    TelegramMessageRequest,
    TelegramSeverity,
)
from homelab_mcp.infrastructure.mcp.server import create_gateway_mcp_server
from homelab_mcp.server import build_gateway_application
from pydantic import SecretStr


@pytest.mark.asyncio
async def test_gateway_exposes_telegram_tools():
    mock_service = AsyncMock()
    mock_telegram = AsyncMock(spec=TelegramClientInterface)
    mock_telegram.send_message.return_value = {"ok": True, "result": {"message_id": 1}}
    mock_telegram.send_alert.return_value = {"ok": True, "result": {"message_id": 2}}
    mock_telegram.set_reaction.return_value = {"ok": True}

    mcp = create_gateway_mcp_server(mock_service, telegram_client=mock_telegram)
    tool_names = [t.name for t in await mcp.list_tools()]

    assert "telegram_send_message" in tool_names
    assert "telegram_send_alert" in tool_names
    assert "telegram_set_reaction" in tool_names


@pytest.mark.asyncio
async def test_gateway_omits_telegram_tools_when_no_client():
    mock_service = AsyncMock()

    mcp = create_gateway_mcp_server(mock_service, telegram_client=None)
    tool_names = [t.name for t in await mcp.list_tools()]

    assert "telegram_send_message" not in tool_names
    assert "telegram_send_alert" not in tool_names
    assert "telegram_set_reaction" not in tool_names


@pytest.mark.asyncio
async def test_gateway_calls_telegram_send_message_tool():
    mock_service = AsyncMock()
    mock_telegram = AsyncMock(spec=TelegramClientInterface)
    mock_telegram.send_message.return_value = {"ok": True, "result": {"message_id": 100}}

    mcp = create_gateway_mcp_server(mock_service, telegram_client=mock_telegram)
    res = await mcp.call_tool(
        "telegram_send_message",
        {
            "text": "Service restored",
            "chat_id": "-10012345",
            "parse_mode": "HTML",
            "reply_to_message_id": 42,
        },
    )

    assert not res.is_error
    assert res.structured_content == {"ok": True, "result": {"message_id": 100}}
    mock_telegram.send_message.assert_awaited_once_with(
        TelegramMessageRequest(
            text="Service restored",
            chat_id="-10012345",
            parse_mode="HTML",
            reply_to_message_id=42,
        )
    )


@pytest.mark.asyncio
async def test_gateway_calls_telegram_set_reaction_tool():
    from homelab_mcp.domain.models.telegram import TelegramReactionRequest

    mock_service = AsyncMock()
    mock_telegram = AsyncMock(spec=TelegramClientInterface)
    mock_telegram.set_reaction.return_value = {"ok": True}

    mcp = create_gateway_mcp_server(mock_service, telegram_client=mock_telegram)
    res = await mcp.call_tool(
        "telegram_set_reaction",
        {"message_id": 42, "emoji": "⚡", "chat_id": "-10012345"},
    )

    assert not res.is_error
    assert res.structured_content == {"ok": True}
    mock_telegram.set_reaction.assert_awaited_once_with(
        TelegramReactionRequest(
            message_id=42,
            emoji="⚡",
            chat_id="-10012345",
        )
    )


@pytest.mark.asyncio
async def test_gateway_calls_telegram_send_alert_tool():
    mock_service = AsyncMock()
    mock_telegram = AsyncMock(spec=TelegramClientInterface)
    mock_telegram.send_alert.return_value = {"ok": True, "result": {"message_id": 101}}

    mcp = create_gateway_mcp_server(mock_service, telegram_client=mock_telegram)
    res = await mcp.call_tool(
        "telegram_send_alert",
        {
            "title": "High Memory Usage",
            "message": "Node memory exceeds 90%",
            "severity": "critical",
            "chat_id": "999888",
        },
    )

    assert not res.is_error
    assert res.structured_content == {"ok": True, "result": {"message_id": 101}}
    mock_telegram.send_alert.assert_awaited_once_with(
        TelegramAlertRequest(
            title="High Memory Usage",
            message="Node memory exceeds 90%",
            severity=TelegramSeverity.CRITICAL,
            chat_id="999888",
        )
    )


@pytest.mark.asyncio
async def test_build_gateway_application_wires_telegram_client_when_configured():
    with patch("homelab_mcp.server.settings") as mock_settings:
        mock_settings.ha_enabled = False
        mock_settings.unifi_enabled = False
        mock_settings.k8s_enabled = False
        mock_settings.telegram_enabled = True
        mock_settings.telegram_bot_token = SecretStr("123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11")
        mock_settings.telegram_default_chat_id = "12345678"
        mock_settings.auth_enabled = False

        service, mcp_app = build_gateway_application()
        tool_names = [t.name for t in await mcp_app.list_tools()]

        assert "telegram_send_message" in tool_names
        assert "telegram_send_alert" in tool_names
        assert "telegram_set_reaction" in tool_names


@pytest.mark.asyncio
async def test_build_gateway_application_skips_telegram_client_when_disabled():
    with patch("homelab_mcp.server.settings") as mock_settings:
        mock_settings.ha_enabled = False
        mock_settings.unifi_enabled = False
        mock_settings.k8s_enabled = False
        mock_settings.telegram_enabled = False
        mock_settings.telegram_bot_token = None
        mock_settings.telegram_default_chat_id = None
        mock_settings.auth_enabled = False

        service, mcp_app = build_gateway_application()
        tool_names = [t.name for t in await mcp_app.list_tools()]

        assert "telegram_send_message" not in tool_names
        assert "telegram_send_alert" not in tool_names
        assert "telegram_set_reaction" not in tool_names
