"""Domain specialist graph nodes for LYOKO StateGraph workflow."""

import logging
from collections.abc import Callable
from typing import Any

from langchain_core.runnables import RunnableConfig
from lyoko.application.chat_manager import ChatManager
from lyoko.application.hitl import ApprovalManager
from lyoko.application.nodes.helpers import make_gate, status_callback
from lyoko.application.tool_gate import GateMode

logger = logging.getLogger("lyoko.workflow.specialist")


def create_specialist_node(
    domain: str,
    specialist: Any,
    mcp_client: Any = None,
    approval_manager: ApprovalManager | None = None,
    chat_manager: ChatManager | None = None,
) -> Callable[[dict[str, Any], RunnableConfig], Any]:
    """Factory creating an inline graph node for a specific domain specialist."""

    async def specialist_node(state: dict[str, Any], config: RunnableConfig) -> dict[str, Any]:
        pending = state.get("pending_delegation")
        if not pending or pending.get("domain") != domain:
            logger.warning(
                "Specialist node '%s' called without matching pending delegation (%s)",
                domain,
                pending,
            )
            return {"pending_delegation": None}

        task = pending.get("task", "")
        mode_str = pending.get("gate_mode", GateMode.READ_ONLY.value)
        gate_mode = GateMode.APPROVAL if mode_str == GateMode.APPROVAL.value else GateMode.READ_ONLY

        gate = make_gate(
            state,
            gate_mode,
            approval_manager=approval_manager,
            chat_manager=chat_manager,
            mcp_client=mcp_client,
        )

        on_status = status_callback(config)
        session_id = state.get("session_id")

        logger.info("Executing specialist node for domain '%s' with task: %s", domain, task)
        try:
            response = await specialist.run(
                prompt=task,
                session_id=session_id,
                authorizer=gate.authorize,
                parent_config=config,
                on_status=on_status,
            )
        except Exception as exc:
            logger.error("Error executing specialist '%s': %s", domain, exc)
            response = f"Specialist error ({domain}): {exc}"

        history = list(state.get("delegation_history") or [])
        history.append(
            {
                "domain": domain,
                "task": task,
                "response": response,
            }
        )

        return {
            "pending_delegation": None,
            "delegation_history": history,
            "actions": list(state.get("actions") or []) + [r.to_dict() for r in gate.records],
        }

    return specialist_node
