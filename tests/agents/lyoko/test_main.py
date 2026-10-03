"""Unit tests for LYOKO application lifespan and composition root."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from lyoko.main import build_domain_specialists, build_supervisor, create_app, lifespan


@pytest.mark.asyncio
async def test_healthz_endpoint():
    app = create_app()
    async with lifespan(app):
        # Without postgres credentials, app state has no checkpointer
        assert app.state.workflow_engine is not None
        assert "kubernetes" in app.state.specialists
        assert "unifi" in app.state.specialists
        assert "homeassistant" in app.state.specialists
        assert "grafana" in app.state.specialists
        assert app.state.supervisor is not None


def test_build_domain_specialists_and_supervisor():
    specialists = build_domain_specialists(mcp_client=None, llm=None)
    assert set(specialists.keys()) == {"kubernetes", "unifi", "homeassistant", "grafana"}
    supervisor = build_supervisor(specialists, llm=None)
    assert supervisor.specialists == specialists


@pytest.mark.asyncio
@patch("lyoko.main.AsyncPostgresSaver")
@patch("lyoko.main.AsyncConnectionPool")
async def test_lifespan_with_postgres_configured(mock_pool_cls, mock_saver_cls):
    mock_pool = MagicMock()
    mock_pool.open = AsyncMock()
    mock_pool.close = AsyncMock()
    mock_pool_cls.return_value = mock_pool

    mock_saver = MagicMock(spec=AsyncPostgresSaver)
    mock_saver.setup = AsyncMock()
    mock_saver_cls.return_value = mock_saver

    with patch("lyoko.main.settings.postgres_password", "testpassword"):
        app = create_app()
        async with lifespan(app):
            mock_pool.open.assert_awaited_once()
            mock_saver.setup.assert_awaited_once()
            assert app.state.checkpointer is mock_saver
            assert app.state.db_pool is mock_pool

        mock_pool.close.assert_awaited_once()
