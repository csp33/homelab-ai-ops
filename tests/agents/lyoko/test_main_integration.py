"""Integration tests for LYOKO application composition root and FastAPI lifespan."""

from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from lyoko.application.hitl import ApprovalManager
from lyoko.infrastructure.mcp.client import FastMCPClient
from lyoko.main import build_chat_manager, create_app


@pytest.mark.asyncio
async def test_app_health_endpoint():
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/healthz")
        assert resp.status_code == 200
        assert resp.json()["status"] == "healthy"
        assert resp.json()["service"] == "lyoko-agent"


@pytest.mark.asyncio
async def test_build_chat_manager_disabled(monkeypatch):
    monkeypatch.setattr("lyoko.config.settings.telegram_enabled", False)
    mcp_client = FastMCPClient()
    approval_mgr = ApprovalManager()
    mgr = build_chat_manager(mcp_client, approval_mgr)
    assert len(mgr.connectors) == 0


@pytest.mark.asyncio
async def test_build_chat_manager_enabled(monkeypatch):
    monkeypatch.setattr("lyoko.config.settings.telegram_enabled", True)
    monkeypatch.setattr("lyoko.config.settings.telegram_bot_token", "123456:fake_token")
    monkeypatch.setattr("lyoko.config.settings.telegram_allowed_user_ids", "111,222")
    monkeypatch.setattr("lyoko.config.settings.telegram_default_chat_id", "111")

    mcp_client = FastMCPClient()
    approval_mgr = ApprovalManager()
    mgr = build_chat_manager(mcp_client, approval_mgr)
    assert len(mgr.connectors) == 1
    assert mgr.connectors[0].is_user_authorized("111") is True
    assert mgr.connectors[0].is_user_authorized("999") is False


@pytest.mark.asyncio
async def test_app_lifespan_lifecycle():
    with (
        patch(
            "lyoko.infrastructure.chat.manager.ChatManager.start_all", new_callable=AsyncMock
        ) as mock_start,
        patch(
            "lyoko.infrastructure.chat.manager.ChatManager.stop_all", new_callable=AsyncMock
        ) as mock_stop,
    ):
        app = create_app()
        async with app.router.lifespan_context(app):
            pass

        mock_start.assert_called_once()
        mock_stop.assert_called_once()
