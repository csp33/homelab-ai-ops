"""LangGraph StateGraph workflow for LYOKO auto-remediation."""

import asyncio
import logging
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from lyoko.application.chat_manager import ChatManager
from lyoko.application.hitl import ApprovalManager
from lyoko.config import settings
from lyoko.domain.interfaces.llm import LLMClientInterface
from lyoko.domain.models.chat import ApprovalAction, ApprovalRequest

logger = logging.getLogger("lyoko.workflow")


class RemediationGraphState(TypedDict, total=False):
    incident_id: str
    chat_id: str
    messages: Annotated[list[Any], add_messages]
    namespace: str
    pod_name: str
    deployment_name: str
    alert_name: str
    diagnostics: dict[str, Any]
    root_cause: str
    action_taken: str
    is_resolved: bool
    requires_escalation: bool
    approval_granted: bool


def create_remediation_workflow(
    mcp_client: Any,
    approval_manager: ApprovalManager | None = None,
    chat_manager: ChatManager | None = None,
    checkpointer: Any = None,
    llm: LLMClientInterface | None = None,
) -> Any:
    """Build LangGraph StateGraph workflow for incident diagnosis and auto-remediation."""

    async def diagnose_node(state: RemediationGraphState) -> dict[str, Any]:
        """Fetch diagnostics from homelab-mcp and evaluate root cause."""
        namespace = state.get("namespace", "default")
        pod_name = state.get("pod_name", "")
        logger.info(f"Diagnosing pod {pod_name} in namespace {namespace}...")

        diag = await mcp_client.call_tool(
            "k8s_get_pod_diagnostics",
            {"namespace": namespace, "pod_name": pod_name, "tail_lines": 40},
        )

        root_cause = ""
        if llm is not None:
            try:
                root_cause = await llm.analyze_incident(
                    alert_name=state.get("alert_name", ""),
                    pod_name=pod_name,
                    namespace=namespace,
                    diagnostics=diag,
                    session_id=state.get("incident_id"),
                )
            except Exception as e:
                logger.warning(
                    "LLM root cause analysis failed: %s; falling back to diagnostic inspection", e
                )

        if not root_cause:
            logs = str(diag.get("logs", "")) if isinstance(diag, dict) else str(diag)
            phase = str(diag.get("phase", "")) if isinstance(diag, dict) else ""
            if "OOMKilled" in logs or "137" in logs or "OOMKilled" in phase:
                root_cause = "Pod terminated with exit code 137 (OOMKilled)."
            else:
                root_cause = f"Pod in {phase} state. Logs: {logs[:100]}"

        return {"diagnostics": diag, "root_cause": root_cause}

    async def request_approval_node(state: RemediationGraphState) -> dict[str, Any]:
        """Request human-in-the-loop approval before applying mutation."""
        root_cause = state.get("root_cause", "")
        is_oom = "OOMKilled" in root_cause or "137" in root_cause
        if not is_oom or state.get("requires_escalation"):
            return {}

        incident_id = (
            state.get("incident_id")
            or f"{state.get('namespace', 'default')}-{state.get('pod_name', 'pod')}"
        )

        if approval_manager is None:
            return {"incident_id": incident_id, "approval_granted": True}

        chat_id = state.get("chat_id") or settings.telegram_default_chat_id or ""
        req = ApprovalRequest(
            incident_id=incident_id,
            title=f"Remediation Approval Required: {state.get('pod_name', '')}",
            details=(
                f"Pod: `{state.get('pod_name', '')}`\n"
                f"Namespace: `{state.get('namespace', '')}`\n"
                f"Alert: {state.get('alert_name', '')}\n"
                f"Root Cause: {state.get('root_cause', 'Unknown')}\n"
                f"Proposed Action: Bump memory to 1Gi"
            ),
            chat_id=chat_id,
            actions=[
                ApprovalAction(action_id="approve", label="✅ Approve (1Gi Bump)", style="primary"),
                ApprovalAction(action_id="reject", label="❌ Deny", style="danger"),
            ],
        )

        if chat_manager is not None:
            await chat_manager.broadcast_approval_request(req)

        response = await approval_manager.wait_for_approval(incident_id)
        if not response.approved:
            logger.warning(
                "Remediation approval rejected for incident %s: %s",
                incident_id,
                response.reason,
            )
            return {
                "incident_id": incident_id,
                "approval_granted": False,
                "requires_escalation": True,
                "action_taken": f"Remediation aborted: {response.reason or 'Approval rejected'}",
            }

        return {"incident_id": incident_id, "approval_granted": True}

    async def remediate_node(state: RemediationGraphState) -> dict[str, Any]:
        """Apply safe remediation if root cause is OOMKilled and approval granted."""
        namespace = state.get("namespace", "default")
        pod_name = state.get("pod_name", "")
        dep_name = state.get("deployment_name") or pod_name.rsplit("-", 2)[0]
        root_cause = state.get("root_cause", "")

        if "OOMKilled" in root_cause or "137" in root_cause:
            if state.get("requires_escalation") or state.get("approval_granted") is False:
                return {
                    "action_taken": state.get(
                        "action_taken", "Remediation aborted: approval rejected or timed out"
                    ),
                    "requires_escalation": True,
                }

            logger.info(f"Applying memory bump to {dep_name} in {namespace}...")
            res = await mcp_client.call_tool(
                "k8s_bump_deployment_resources",
                {
                    "namespace": namespace,
                    "deployment_name": dep_name,
                    "memory_limit": "1Gi",
                    "memory_request": "512Mi",
                },
            )
            return {"action_taken": f"Bumped memory to 1Gi: {res}"}

        return {
            "action_taken": "No automated mutation applied (requires human inspection)",
            "requires_escalation": True,
        }

    async def verify_node(state: RemediationGraphState) -> dict[str, Any]:
        """Wait and verify pod status after remediation."""
        if state.get("requires_escalation"):
            return {"is_resolved": False}

        logger.info(f"Waiting {settings.verification_delay_seconds}s for pod stabilization...")
        await asyncio.sleep(settings.verification_delay_seconds)

        diag = await mcp_client.call_tool(
            "k8s_get_pod_diagnostics",
            {
                "namespace": state.get("namespace", "default"),
                "pod_name": state.get("pod_name", ""),
                "tail_lines": 10,
            },
        )
        is_running = (
            diag.get("phase") in ["Running", "Pending"] if isinstance(diag, dict) else False
        )
        return {"is_resolved": is_running}

    async def notify_node(state: RemediationGraphState) -> dict[str, Any]:
        """Log final structured incident report and broadcast via chat connector."""
        status_icon = "RESOLVED" if state.get("is_resolved") else "ESCALATED / REQUIRES ACTION"
        summary = (
            f"📋 *[LYOKO Incident Report]*\n\n"
            f"• *Status:* {status_icon}\n"
            f"• *Namespace:* `{state.get('namespace', '')}`\n"
            f"• *Pod:* `{state.get('pod_name', '')}`\n"
            f"• *Alert:* {state.get('alert_name', '')}\n"
            f"• *Root Cause:* {state.get('root_cause', 'Unknown')}\n"
            f"• *Action Taken:* {state.get('action_taken', 'None')}"
        )
        logger.info(summary)
        if chat_manager is not None:
            chat_id = state.get("chat_id") or settings.telegram_default_chat_id or ""
            await chat_manager.broadcast_message(chat_id=chat_id, text=summary)
        return {}

    # Assemble StateGraph
    workflow = StateGraph(RemediationGraphState)
    workflow.add_node("diagnose", diagnose_node)
    workflow.add_node("request_approval", request_approval_node)
    workflow.add_node("remediate", remediate_node)
    workflow.add_node("verify", verify_node)
    workflow.add_node("notify", notify_node)

    workflow.add_edge(START, "diagnose")
    workflow.add_edge("diagnose", "request_approval")
    workflow.add_edge("request_approval", "remediate")
    workflow.add_edge("remediate", "verify")
    workflow.add_edge("verify", "notify")
    workflow.add_edge("notify", END)

    return workflow.compile(checkpointer=checkpointer)
