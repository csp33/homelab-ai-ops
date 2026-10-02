import asyncio
from unittest.mock import AsyncMock

import pytest
from lyoko.application.hitl import ApprovalManager
from lyoko.application.workflow import create_remediation_workflow
from lyoko.domain.interfaces.llm import LLMClientInterface
from lyoko.domain.models.chat import ApprovalResponse


@pytest.fixture(autouse=True)
def mock_verification_delay(monkeypatch):
    monkeypatch.setattr("lyoko.application.workflow.settings.verification_delay_seconds", 0)


@pytest.mark.asyncio
async def test_workflow_oom_approval_and_remediation():
    mock_mcp = AsyncMock()
    mock_mcp.call_tool.side_effect = [
        {"phase": "CrashLoopBackOff", "logs": "OOMKilled exit 137"},  # diagnose
        {"status": "patched"},  # remediate
        {"phase": "Running"},  # verify
    ]
    mock_chat = AsyncMock()
    approval_mgr = ApprovalManager()

    mock_llm = AsyncMock(spec=LLMClientInterface)
    mock_llm.analyze_incident.return_value = (
        "Root cause: Pod terminated with exit code 137 (OOMKilled)."
    )

    workflow = create_remediation_workflow(
        mcp_client=mock_mcp,
        approval_manager=approval_mgr,
        chat_manager=mock_chat,
        llm=mock_llm,
    )

    async def auto_approve():
        await asyncio.sleep(0.05)
        approval_mgr.resolve_approval(
            ApprovalResponse(
                incident_id="test-inc",
                approved=True,
                user_id="admin",
            )
        )

    asyncio.create_task(auto_approve())

    initial_state = {
        "incident_id": "test-inc",
        "namespace": "default",
        "pod_name": "web-app-12345",
        "deployment_name": "web-app",
        "alert_name": "KubePodCrashLooping",
        "messages": [],
    }

    final_state = await workflow.ainvoke(initial_state)
    assert final_state["is_resolved"] is True
    assert "Bumped memory" in final_state["action_taken"]
    mock_chat.broadcast_approval_request.assert_called_once()
    mock_chat.broadcast_message.assert_called_once()


@pytest.mark.asyncio
async def test_workflow_oom_approval_rejected():
    mock_mcp = AsyncMock()
    mock_mcp.call_tool.side_effect = [
        {"phase": "CrashLoopBackOff", "logs": "OOMKilled exit 137"},  # diagnose
    ]
    mock_chat = AsyncMock()
    approval_mgr = ApprovalManager()

    mock_llm = AsyncMock(spec=LLMClientInterface)
    mock_llm.analyze_incident.return_value = (
        "Root cause: Pod terminated with exit code 137 (OOMKilled)."
    )

    workflow = create_remediation_workflow(
        mcp_client=mock_mcp,
        approval_manager=approval_mgr,
        chat_manager=mock_chat,
        llm=mock_llm,
    )

    async def auto_reject():
        await asyncio.sleep(0.05)
        approval_mgr.resolve_approval(
            ApprovalResponse(
                incident_id="test-reject-inc",
                approved=False,
                user_id="admin",
                reason="Manual denial by operator",
            )
        )

    asyncio.create_task(auto_reject())

    initial_state = {
        "incident_id": "test-reject-inc",
        "namespace": "prod",
        "pod_name": "api-service-9999",
        "deployment_name": "api-service",
        "alert_name": "KubePodCrashLooping",
        "messages": [],
    }

    final_state = await workflow.ainvoke(initial_state)
    assert final_state["is_resolved"] is False
    assert final_state["requires_escalation"] is True
    assert "aborted" in final_state["action_taken"].lower()
    mock_chat.broadcast_approval_request.assert_called_once()
    mock_chat.broadcast_message.assert_called_once()
    assert mock_mcp.call_tool.await_count == 1  # Only diagnose was called


@pytest.mark.asyncio
async def test_workflow_oom_approval_timeout():
    mock_mcp = AsyncMock()
    mock_mcp.call_tool.side_effect = [
        {"phase": "CrashLoopBackOff", "logs": "OOMKilled exit 137"},  # diagnose
    ]
    mock_chat = AsyncMock()
    approval_mgr = ApprovalManager(default_timeout_seconds=0.05)

    mock_llm = AsyncMock(spec=LLMClientInterface)
    mock_llm.analyze_incident.return_value = (
        "Root cause: Pod terminated with exit code 137 (OOMKilled)."
    )

    workflow = create_remediation_workflow(
        mcp_client=mock_mcp,
        approval_manager=approval_mgr,
        chat_manager=mock_chat,
        llm=mock_llm,
    )

    initial_state = {
        "incident_id": "test-timeout-inc",
        "namespace": "prod",
        "pod_name": "api-service-9999",
        "deployment_name": "api-service",
        "alert_name": "KubePodCrashLooping",
        "messages": [],
    }

    final_state = await workflow.ainvoke(initial_state)
    assert final_state["is_resolved"] is False
    assert final_state["requires_escalation"] is True
    assert "aborted" in final_state["action_taken"].lower()
    mock_chat.broadcast_approval_request.assert_called_once()
    mock_chat.broadcast_message.assert_called_once()
    assert mock_mcp.call_tool.await_count == 1
