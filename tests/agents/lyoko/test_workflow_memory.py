"""Tests for LangGraph workflow integration with Memory and Operator Feedback."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from lyoko.application.workflow import create_remediation_workflow
from lyoko.domain.models.memory import MemoryEntry, MemoryQueryResult


@pytest.mark.asyncio
@patch("lyoko.application.workflow.ChatOpenAI")
async def test_workflow_diagnose_injects_operator_memory(mock_chat_openai_cls):
    """Verify diagnose_node searches memory and injects past lessons into the prompt."""
    mock_llm = MagicMock()
    mock_llm.ainvoke = AsyncMock(
        return_value=MagicMock(content="Root cause: OOMKilled following operator guidelines.")
    )
    mock_chat_openai_cls.return_value = mock_llm

    mock_mcp = AsyncMock()
    mock_mcp.call_tool.return_value = {
        "pod_name": "influxdb-0",
        "phase": "Running",
        "logs": "fatal error: out of memory (exit code 137)",
    }

    mock_memory_repo = AsyncMock()
    past_memory = MemoryEntry(
        id=1,
        namespace="monitoring",
        service_name="influxdb",
        alert_name="PodCrashLooping",
        incident_pattern="OOMKilled 137",
        operator_feedback="Do NOT increase RAM limit. Compact WAL segments first.",
        action_rule="Do not bump memory; truncate WAL",
    )
    mock_memory_repo.search_memories.return_value = [
        MemoryQueryResult(memory=past_memory, similarity=0.95)
    ]

    mock_embeddings = AsyncMock()
    mock_embeddings.embed_text.return_value = [0.05] * 1536

    with patch("lyoko.application.workflow.settings.verification_delay_seconds", 0):
        workflow = create_remediation_workflow(
            mcp_client=mock_mcp,
            memory_repository=mock_memory_repo,
            embeddings_service=mock_embeddings,
        )

        initial_state = {
            "messages": [],
            "namespace": "monitoring",
            "pod_name": "influxdb-0",
            "deployment_name": "influxdb",
            "alert_name": "PodCrashLooping",
            "diagnostics": {},
            "root_cause": "",
            "action_taken": "",
            "is_resolved": False,
            "requires_escalation": False,
        }

        # Execute workflow
        result = await workflow.ainvoke(initial_state)

        # Verify memory search was called with correct context
        assert mock_memory_repo.search_memories.called
        assert mock_embeddings.embed_text.called

        # State should reflect memory context and diagnostics
        assert "diagnostics" in result
        assert "matched_memories" in result
        assert len(result["matched_memories"]) == 1
        assert (
            result["matched_memories"][0]["operator_feedback"]
            == "Do NOT increase RAM limit. Compact WAL segments first."
        )

        # Because operator rule says "Do NOT increase RAM", remediation should be skipped
        assert "Skipped automated mutation per operator rule" in result["action_taken"]
        assert result["requires_escalation"] is True
