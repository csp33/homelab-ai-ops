"""Remediate node: executes the diagnosis plan with approval-gated tools."""

import logging
from collections.abc import Callable
from typing import Any

from langchain_core.runnables import RunnableConfig
from lyoko.application.use_cases.remediate_incident import RemediateIncidentUseCase
from lyoko.domain.interfaces.approval import ApprovalManagerInterface
from lyoko.domain.interfaces.chat_service import ChatServiceInterface
from lyoko.domain.interfaces.llm import LLMClientInterface
from lyoko.domain.interfaces.mcp import MCPClientInterface
from lyoko.domain.interfaces.supervisor import SupervisorInterface

logger = logging.getLogger("lyoko.workflow.incident")


def create_remediate_node(
    mcp_client: MCPClientInterface | None,
    llm: LLMClientInterface | None,
    supervisor: SupervisorInterface | None = None,
    approval_manager: ApprovalManagerInterface | None = None,
    chat_manager: ChatServiceInterface | None = None,
) -> Callable[[dict[str, Any], RunnableConfig], Any]:
    """Factory creating the remediate node handler."""
    use_case = RemediateIncidentUseCase(
        mcp_client=mcp_client,
        llm=llm,
        supervisor=supervisor,
        approval_manager=approval_manager,
        chat_manager=chat_manager,
    )

    async def remediate_node(state: dict[str, Any], config: RunnableConfig) -> dict[str, Any]:
        """Carry out the plan. State-changing tools wait for operator approval."""
        return await use_case.execute(state, config=config)

    return remediate_node
