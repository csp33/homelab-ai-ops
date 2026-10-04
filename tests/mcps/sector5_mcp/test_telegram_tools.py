"""Tests for the Telegram in-process domain provider and its gateway wiring."""

from unittest.mock import AsyncMock, patch

import pytest
from pydantic import SecretStr
from sector5_mcp.domain.interfaces.telegram import TelegramClientInterface
from sector5_mcp.domain.models.telegram import (
    TelegramAlertRequest,
    TelegramMessageRequest,
    TelegramReactionRequest,
    TelegramSeverity,
)
from sector5_mcp.domain.models.upstream import UpstreamType
from sector5_mcp.infrastructure.upstream.telegram import TelegramUpstreamClient
from sector5_mcp.server import build_gateway_application


def _mock_client() -> AsyncMock:
    mock = AsyncMock(spec=TelegramClientInterface)
    mock.send_message.return_value = {"ok": True, "result": {"message_id": 1}}
    mock.send_alert.return_value = {"ok": True, "result": {"message_id": 2}}
    mock.set_reaction.return_value = {"ok": True}
    return mock


@pytest.mark.asyncio
async def test_telegram_provider_lists_domain_tools():
    provider = TelegramUpstreamClient(_mock_client())
    tools = await provider.list_tools()

    assert {t.name for t in tools} == {
        "telegram_send_message",
        "telegram_send_alert",
        "telegram_set_reaction",
    }
    assert all(t.upstream_type == UpstreamType.TELEGRAM for t in tools)


@pytest.mark.asyncio
async def test_telegram_provider_dispatches_send_message():
    client = _mock_client()
    provider = TelegramUpstreamClient(client)

    result = await provider.call_tool(
        "telegram_send_message",
        {
            "text": "Service restored",
            "chat_id": "-10012345",
            "parse_mode": "HTML",
            "reply_to_message_id": 42,
        },
    )

    assert not result.is_error
    assert result.content == {"ok": True, "result": {"message_id": 1}}
    client.send_message.assert_awaited_once_with(
        TelegramMessageRequest(
            text="Service restored",
            chat_id="-10012345",
            parse_mode="HTML",
            reply_to_message_id=42,
        )
    )


@pytest.mark.asyncio
async def test_telegram_provider_dispatches_alert_with_severity():
    client = _mock_client()
    provider = TelegramUpstreamClient(client)

    await provider.call_tool(
        "telegram_send_alert",
        {
            "title": "High Memory Usage",
            "message": "Node memory exceeds 90%",
            "severity": "critical",
            "chat_id": "999888",
        },
    )

    client.send_alert.assert_awaited_once_with(
        TelegramAlertRequest(
            title="High Memory Usage",
            message="Node memory exceeds 90%",
            severity=TelegramSeverity.CRITICAL,
            chat_id="999888",
        )
    )


@pytest.mark.asyncio
async def test_telegram_provider_defaults_unknown_severity_to_warning():
    client = _mock_client()
    provider = TelegramUpstreamClient(client)

    await provider.call_tool(
        "telegram_send_alert",
        {"title": "t", "message": "m", "severity": "nonsense"},
    )

    request = client.send_alert.await_args.args[0]
    assert request.severity == TelegramSeverity.WARNING


@pytest.mark.asyncio
async def test_telegram_provider_dispatches_reaction():
    client = _mock_client()
    provider = TelegramUpstreamClient(client)

    await provider.call_tool(
        "telegram_set_reaction",
        {"message_id": 42, "emoji": "⚡", "chat_id": "-10012345"},
    )

    client.set_reaction.assert_awaited_once_with(
        TelegramReactionRequest(message_id=42, emoji="⚡", chat_id="-10012345")
    )


@pytest.mark.asyncio
async def test_telegram_provider_unknown_tool_is_error():
    provider = TelegramUpstreamClient(_mock_client())
    result = await provider.call_tool("telegram_nope", {})
    assert result.is_error


@pytest.mark.asyncio
async def test_build_gateway_application_registers_telegram_domain_when_configured():
    with patch("sector5_mcp.server.settings") as mock_settings:
        mock_settings.ha_enabled = False
        mock_settings.unifi_enabled = False
        mock_settings.k8s_enabled = False
        mock_settings.grafana_enabled = False
        mock_settings.github_enabled = False
        mock_settings.telegram_enabled = True
        mock_settings.telegram_bot_token = SecretStr("123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11")
        mock_settings.telegram_default_chat_id = "12345678"
        mock_settings.auth_enabled = False

        service, _mcp_app = build_gateway_application()
        tools = await service.discover_tools()

        names = {t.name for t in tools}
        assert {"telegram_send_message", "telegram_send_alert", "telegram_set_reaction"} <= names
        assert any(t.upstream_type == UpstreamType.TELEGRAM for t in tools)


@pytest.mark.asyncio
async def test_build_gateway_application_skips_telegram_domain_when_disabled():
    with patch("sector5_mcp.server.settings") as mock_settings:
        mock_settings.ha_enabled = False
        mock_settings.unifi_enabled = False
        mock_settings.k8s_enabled = False
        mock_settings.grafana_enabled = False
        mock_settings.github_enabled = False
        mock_settings.telegram_enabled = False
        mock_settings.telegram_bot_token = None
        mock_settings.telegram_default_chat_id = None
        mock_settings.auth_enabled = False

        service, _mcp_app = build_gateway_application()
        tools = await service.discover_tools()

        assert "telegram_send_message" not in {t.name for t in tools}
