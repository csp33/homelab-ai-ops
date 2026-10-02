"""Unit tests for LYOKO LangGraph StateGraph workflow."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from lyoko.application.workflow import create_remediation_workflow
from lyoko.domain.interfaces.llm import LLMClientInterface


@pytest.mark.asyncio
async def test_remediation_workflow_oom_path():
    # Mock LLM responding with OOM root cause
    mock_llm = AsyncMock(spec=LLMClientInterface)
    mock_llm.analyze_incident.return_value = (
        "Root cause: Pod terminated with exit code 137 (OOMKilled)."
    )

    # Mock MCP Client
    mock_mcp = MagicMock()
    mock_mcp.call_tool = AsyncMock(
        side_effect=[
            # 1. k8s_get_pod_diagnostics (diagnose node)
            {"phase": "Running", "logs": "fatal error: runtime: out of memory"},
            # 2. k8s_bump_deployment_resources (remediate node)
            {"status": "patched", "limits": {"memory": "1Gi"}},
            # 3. k8s_get_pod_diagnostics (verify node)
            {"phase": "Running", "ready": True},
        ]
    )

    with patch("lyoko.application.workflow.settings.verification_delay_seconds", 0):
        workflow = create_remediation_workflow(mcp_client=mock_mcp, llm=mock_llm)

        initial_state = {
            "namespace": "media",
            "pod_name": "radarr-79dfb8bf7-x82k",
            "deployment_name": "radarr",
            "alert_name": "KubePodCrashLooping",
            "messages": [],
            "diagnostics": {},
            "root_cause": "",
            "action_taken": "",
            "is_resolved": False,
            "requires_escalation": False,
        }

        final_state = await workflow.ainvoke(initial_state)

        assert "OOMKilled" in final_state["root_cause"]
        assert "Bumped memory to 1Gi" in final_state["action_taken"]
        assert final_state["is_resolved"] is True
        assert final_state["requires_escalation"] is False
        mock_llm.analyze_incident.assert_awaited_once()


@pytest.mark.asyncio
async def test_remediation_workflow_escalation_path():
    # Mock LLM responding with Misconfiguration root cause
    mock_llm = AsyncMock(spec=LLMClientInterface)
    mock_llm.analyze_incident.return_value = (
        "Root cause: Misconfiguration - invalid database credentials."
    )

    # Mock MCP Client
    mock_mcp = MagicMock()
    mock_mcp.call_tool = AsyncMock(
        return_value={"phase": "CrashLoopBackOff", "logs": "Access denied for user 'root'"}
    )

    with patch("lyoko.application.workflow.settings.verification_delay_seconds", 0):
        workflow = create_remediation_workflow(mcp_client=mock_mcp, llm=mock_llm)

        initial_state = {
            "namespace": "default",
            "pod_name": "custom-app-12345",
            "deployment_name": "custom-app",
            "alert_name": "KubePodCrashLooping",
            "messages": [],
            "diagnostics": {},
            "root_cause": "",
            "action_taken": "",
            "is_resolved": False,
            "requires_escalation": False,
        }

        final_state = await workflow.ainvoke(initial_state)

        assert "Misconfiguration" in final_state["root_cause"]
        assert "requires human inspection" in final_state["action_taken"]
        assert final_state["is_resolved"] is False
        assert final_state["requires_escalation"] is True


@pytest.mark.asyncio
async def test_remediation_workflow_with_checkpointer():
    from langgraph.checkpoint.memory import MemorySaver

    mock_llm = AsyncMock(spec=LLMClientInterface)
    mock_llm.analyze_incident.return_value = (
        "Root cause: Pod terminated with exit code 137 (OOMKilled)."
    )

    mock_mcp = MagicMock()
    mock_mcp.call_tool = AsyncMock(
        side_effect=[
            {"phase": "Running", "logs": "out of memory"},
            {"status": "patched"},
            {"phase": "Running"},
        ]
    )

    checkpointer = MemorySaver()
    workflow = create_remediation_workflow(
        mcp_client=mock_mcp, checkpointer=checkpointer, llm=mock_llm
    )

    initial_state = {
        "namespace": "media",
        "pod_name": "sonarr-12345",
        "deployment_name": "sonarr",
        "alert_name": "KubePodCrashLooping",
        "messages": [],
        "diagnostics": {},
        "root_cause": "",
        "action_taken": "",
        "is_resolved": False,
        "requires_escalation": False,
    }

    config = {"configurable": {"thread_id": "incident-sonarr-12345"}}
    with patch("lyoko.application.workflow.settings.verification_delay_seconds", 0):
        final_state = await workflow.ainvoke(initial_state, config=config)

    assert final_state["is_resolved"] is True

    # Verify checkpointer saved state
    saved_state = await workflow.aget_state(config)
    assert (
        saved_state.values["root_cause"]
        == "Root cause: Pod terminated with exit code 137 (OOMKilled)."
    )
