"""LangGraph StateGraph workflow for LYOKO auto-remediation."""

import asyncio
import logging
from typing import Annotated, Any, TypedDict

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from lyoko.config import settings

logger = logging.getLogger("lyoko.workflow")


class RemediationGraphState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    namespace: str
    pod_name: str
    deployment_name: str
    alert_name: str
    diagnostics: dict[str, Any]
    root_cause: str
    action_taken: str
    is_resolved: bool
    requires_escalation: bool


SYSTEM_PROMPT = """You are LYOKO (Live Yaml Optimization & K8s Orchestration), the autonomous remediation agent.
Analyze pod failure events, diagnose root causes (e.g., OOMKilled, CrashLoopBackOff), and provide precise recommendations."""


def create_remediation_workflow(mcp_client: Any) -> Any:
    """Build LangGraph StateGraph workflow for incident diagnosis and auto-remediation."""
    model = ChatOpenAI(model=settings.openai_model, temperature=0)

    async def diagnose_node(state: RemediationGraphState) -> dict[str, Any]:
        """Fetch diagnostics from homelab-mcp."""
        namespace = state["namespace"]
        pod_name = state["pod_name"]
        logger.info(f"Diagnosing pod {pod_name} in namespace {namespace}...")

        diag = await mcp_client.call_tool(
            "k8s_get_pod_diagnostics",
            {"namespace": namespace, "pod_name": pod_name, "tail_lines": 40},
        )

        prompt = f"""
        Alert: {state["alert_name"]}
        Target Pod: {pod_name} (Namespace: {namespace})
        Diagnostics: {diag}

        Identify the root cause in 1-2 sentences. Is it OOMKilled, Misconfiguration, CrashLoop, or Unknown?
        """
        response = await model.ainvoke(
            [SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=prompt)]
        )
        root_cause = response.content

        return {"diagnostics": diag, "root_cause": root_cause}

    async def remediate_node(state: RemediationGraphState) -> dict[str, Any]:
        """Apply safe remediation if root cause is OOMKilled."""
        namespace = state["namespace"]
        dep_name = state.get("deployment_name") or state["pod_name"].rsplit("-", 2)[0]
        root_cause = state["root_cause"]

        if "OOMKilled" in root_cause or "137" in root_cause:
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
            {"namespace": state["namespace"], "pod_name": state["pod_name"], "tail_lines": 10},
        )
        is_running = diag.get("phase") in ["Running", "Pending"]
        return {"is_resolved": is_running}

    async def notify_node(state: RemediationGraphState) -> dict[str, Any]:
        """Log final structured incident report."""
        status_icon = "RESOLVED" if state.get("is_resolved") else "ESCALATED / REQUIRES ACTION"
        logger.info(
            f"[LYOKO Incident Summary]\n"
            f"Status: {status_icon}\n"
            f"Namespace: {state['namespace']}\n"
            f"Pod: {state['pod_name']}\n"
            f"Alert: {state['alert_name']}\n"
            f"Root Cause: {state.get('root_cause', 'Unknown')}\n"
            f"Action: {state.get('action_taken', 'None')}"
        )
        return {}

    # Assemble StateGraph
    workflow = StateGraph(RemediationGraphState)
    workflow.add_node("diagnose", diagnose_node)
    workflow.add_node("remediate", remediate_node)
    workflow.add_node("verify", verify_node)
    workflow.add_node("notify", notify_node)

    workflow.add_edge(START, "diagnose")
    workflow.add_edge("diagnose", "remediate")
    workflow.add_edge("remediate", "verify")
    workflow.add_edge("verify", "notify")
    workflow.add_edge("notify", END)

    return workflow.compile()
