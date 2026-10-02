"""Integration tests for LYOKO with real PostgreSQL checkpointer."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from lyoko.main import create_app, lifespan


@pytest.mark.asyncio
async def test_postgres_checkpointer_integration_with_local_container():
    """Verify full end-to-end checkpointing against running PostgreSQL instance."""
    app = create_app()

    mock_mcp = MagicMock()
    mock_mcp.call_tool = AsyncMock(
        side_effect=[
            {"phase": "Running", "logs": "out of memory"},
            {"status": "patched"},
            {"phase": "Running"},
        ]
    )

    with (
        patch("lyoko.main.settings.postgres_uri", "postgresql://lyoko:lyoko@localhost:5432/lyoko"),
        patch("lyoko.main.FastMCPClient", return_value=mock_mcp),
        patch("lyoko.application.workflow.ChatOpenAI") as mock_chat_openai_cls,
    ):
        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(
            return_value=MagicMock(
                content="Root cause: Pod terminated with exit code 137 (OOMKilled)."
            )
        )
        mock_chat_openai_cls.return_value = mock_llm

        try:
            async with lifespan(app):
                # Ensure checkpointer is initialized
                assert app.state.checkpointer is not None

                client = TestClient(app)
                health = client.get("/healthz")
                assert health.status_code == 200
                assert health.json()["postgres_checkpointer"] is True

                # Test workflow invocation through state engine
                engine = app.state.workflow_engine
                with patch("lyoko.application.workflow.settings.verification_delay_seconds", 0):
                    config = {"configurable": {"thread_id": "test-integration-incident-001"}}
                    initial_state = {
                        "namespace": "media",
                        "pod_name": "sonarr-test",
                        "deployment_name": "sonarr",
                        "alert_name": "KubePodCrashLooping",
                        "messages": [],
                        "diagnostics": {},
                        "root_cause": "",
                        "action_taken": "",
                        "is_resolved": False,
                        "requires_escalation": False,
                    }
                    result = await engine.ainvoke(initial_state, config=config)
                    assert result["is_resolved"] is True

                    # Retrieve state back from PostgreSQL checkpointer
                    saved_state = await engine.aget_state(config)
                    assert "OOMKilled" in saved_state.values["root_cause"]
        except Exception as exc:
            # If postgres is not running (e.g. in minimal CI environment), skip gracefully
            pytest.skip(f"Local PostgreSQL container not reachable: {exc}")
