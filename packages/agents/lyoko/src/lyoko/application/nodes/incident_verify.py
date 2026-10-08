"""Verify node: read-only re-check that a remediated incident is actually resolved."""

import logging
from collections.abc import Callable
from typing import Any

from langchain_core.runnables import RunnableConfig
from lyoko.application.use_cases.verify_incident import VerifyIncidentUseCase
from lyoko.domain.interfaces.approval import ApprovalManagerInterface
from lyoko.domain.interfaces.chat_service import ChatServiceInterface
from lyoko.domain.interfaces.llm import LLMClientInterface
from lyoko.domain.interfaces.mcp import MCPClientInterface
from lyoko.domain.interfaces.supervisor import SupervisorInterface

logger = logging.getLogger("lyoko.workflow.incident")


def create_verify_node(
    mcp_client: MCPClientInterface | None,
    llm: LLMClientInterface | None,
    supervisor: SupervisorInterface | None = None,
    approval_manager: ApprovalManagerInterface | None = None,
    chat_manager: ChatServiceInterface | None = None,
    delay_seconds: float | None = None,
) -> Callable[[dict[str, Any], RunnableConfig], Any]:
    """Factory creating the verify node handler."""
    use_case = VerifyIncidentUseCase(
        mcp_client=mcp_client,
        llm=llm,
        supervisor=supervisor,
        approval_manager=approval_manager,
        chat_manager=chat_manager,
        delay_seconds=delay_seconds,
    )

    async def verify_node(state: dict[str, Any], config: RunnableConfig) -> dict[str, Any]:
        """Check, read-only, that the incident is actually resolved."""
        return await use_case.execute(state, config=config)

    return verify_node
