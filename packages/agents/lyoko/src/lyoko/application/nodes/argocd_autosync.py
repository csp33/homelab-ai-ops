"""Fast-path triage node for a known Argo CD OutOfSync + autosync-disabled alert.

Instead of spending a multi-agent LLM investigation on a one-field, reversible change, this node
reads the Application, and when autosync is disabled it enables it directly through the same
``ToolGate`` policy (so the change still needs operator approval) and verifies the result
deterministically. Anything it does not recognize falls through to the normal ``diagnose`` node.
"""

import asyncio
import logging
from collections.abc import Callable
from typing import Any

from langchain_core.runnables import RunnableConfig
from lyoko.application.argocd_outofsync import (
    autosync_disabled,
    enable_autosync,
    has_sync_error,
    is_synced_and_healthy,
    manifest_from_tool_result,
    manifest_to_yaml,
    parse_outofsync_app,
)
from lyoko.application.chat_manager import ChatManager
from lyoko.application.hitl import ApprovalManager
from lyoko.application.nodes.helpers import is_message, make_gate, status_callback
from lyoko.application.tool_gate import GateMode
from lyoko.config import settings
from lyoko.domain.interfaces.mcp import MCPClientInterface

logger = logging.getLogger("lyoko.workflow.autosync")

# Argo CD reconciles asynchronously after the manifest change, so poll for a bounded time.
_VERIFY_ATTEMPTS = 6

TRIAGE_DIAGNOSE = "diagnose"
TRIAGE_HANDLED = "handled"

_GET_TOOL = "k8s_resources_get"
_APPLY_TOOL = "k8s_resources_create_or_update"
_APPLICATION = {
    "apiVersion": "argoproj.io/v1alpha1",
    "kind": "Application",
    "namespace": "argocd",
}


def choose_triage(state: dict[str, Any]) -> str:
    """Route a handled fast-path incident to notify, otherwise continue to diagnose."""
    return TRIAGE_HANDLED if state.get("triage") == TRIAGE_HANDLED else TRIAGE_DIAGNOSE


def _status_line(manifest: dict[str, Any]) -> str:
    status = manifest.get("status") or {}
    sync = (status.get("sync") or {}).get("status", "Unknown")
    health = (status.get("health") or {}).get("status", "Unknown")
    return f"sync={sync} health={health}"


def create_argocd_autosync_node(
    mcp_client: MCPClientInterface | None,
    approval_manager: ApprovalManager | None = None,
    chat_manager: ChatManager | None = None,
) -> Callable[[dict[str, Any], RunnableConfig], Any]:
    """Factory creating the deterministic Argo CD autosync triage node."""

    async def argocd_autosync_node(state: dict[str, Any], config: RunnableConfig) -> dict[str, Any]:
        if mcp_client is None or not is_message(state):
            return {"triage": TRIAGE_DIAGNOSE}

        app = parse_outofsync_app(state.get("text", ""))
        if not app:
            return {"triage": TRIAGE_DIAGNOSE}

        on_status = status_callback(config)

        async def report(step: str) -> None:
            if on_status is not None:
                try:
                    await on_status(step)
                except Exception:  # a status update must never break the fast path
                    logger.debug("Failed to report autosync status step '%s'.", step)

        logger.info("Autosync fast-path: checking application '%s'.", app)
        await report(f"🔎 Checking Argo CD autosync for {app}")
        get_args = {**_APPLICATION, "name": app}
        try:
            manifest = manifest_from_tool_result(await mcp_client.call_tool(_GET_TOOL, get_args))
        except Exception as exc:
            logger.warning("Autosync fast-path read failed for %s: %s", app, exc)
            return {"triage": TRIAGE_DIAGNOSE}

        if manifest is None or not autosync_disabled(manifest) or has_sync_error(manifest):
            logger.info(
                "Autosync fast-path not applicable for '%s' (autosync already on or a sync error).",
                app,
            )
            return {"triage": TRIAGE_DIAGNOSE}

        plan = f"Enable Argo CD autosync for application `{app}` (prune + selfHeal)."
        root_cause = (
            f"The Argo CD application `{app}` is OutOfSync because autosync is disabled "
            "(`spec.syncPolicy.automated`). Without autosync, drift is never reconciled."
        )
        logger.info(
            "Autosync fast-path: '%s' has autosync disabled; requesting operator approval.", app
        )
        await report(f"⏳ Waiting for approval to enable autosync on {app}")
        gate = make_gate(
            state,
            GateMode.APPROVAL,
            approval_manager=approval_manager,
            chat_manager=chat_manager,
            plan=plan,
            mcp_client=mcp_client,
        )
        resource = manifest_to_yaml(enable_autosync(manifest))
        refusal = await gate.authorize(_APPLY_TOOL, {"resource": resource})
        actions = [record.to_dict() for record in gate.records]

        if refusal is not None:
            logger.info("Autosync fast-path: '%s' not approved: %s", app, refusal)
            return {
                "triage": TRIAGE_HANDLED,
                "root_cause": root_cause,
                "plan": plan,
                "action_taken": f"Remediation aborted: {refusal}",
                "actions": actions,
                "requires_escalation": True,
                "is_resolved": False,
            }

        await report(f"🛠 Enabling autosync on {app}")
        try:
            await mcp_client.call_tool(_APPLY_TOOL, {"resource": resource})
        except Exception as exc:
            logger.error("Autosync fast-path apply failed for %s: %s", app, exc, exc_info=True)
            return {
                "triage": TRIAGE_HANDLED,
                "root_cause": root_cause,
                "plan": plan,
                "action_taken": f"Remediation failed: {exc}",
                "actions": actions,
                "requires_escalation": True,
                "is_resolved": False,
            }

        verification = ""
        resolved = False
        for attempt in range(_VERIFY_ATTEMPTS):
            await report(
                f"🔍 Verifying {app} is Synced and Healthy"
                + (f" ({attempt}/{_VERIFY_ATTEMPTS - 1})" if attempt else "")
            )
            await asyncio.sleep(settings.verification_delay_seconds)
            try:
                after = manifest_from_tool_result(await mcp_client.call_tool(_GET_TOOL, get_args))
            except Exception as exc:
                logger.warning("Autosync fast-path verification failed for %s: %s", app, exc)
                break
            if after is None:
                break
            resolved = is_synced_and_healthy(after)
            verification = f"Application `{app}` now {_status_line(after)}."
            if resolved:
                break

        logger.info("Autosync fast-path: '%s' resolved=%s (%s).", app, resolved, verification)
        return {
            "triage": TRIAGE_HANDLED,
            "root_cause": root_cause,
            "plan": plan,
            "action_taken": f"Enabled Argo CD autosync for `{app}` (prune + selfHeal).",
            "actions": actions,
            "requires_escalation": not resolved,
            "is_resolved": resolved,
            "verification": verification,
        }

    return argocd_autosync_node
