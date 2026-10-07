"""Verify node: read-only re-check that a remediated incident is actually resolved."""

import logging
from collections.abc import Callable
from typing import Any

from langchain_core.runnables import RunnableConfig
from lyoko.application.chat_manager import ChatManager
from lyoko.application.hitl import ApprovalManager
from lyoko.domain.interfaces.llm import LLMClientInterface

logger = logging.getLogger("lyoko.workflow.incident")


def create_verify_node(
    mcp_client: Any,
    llm: LLMClientInterface | None,
    supervisor: Any = None,
    approval_manager: ApprovalManager | None = None,
    chat_manager: ChatManager | None = None,
) -> Callable[[dict[str, Any], RunnableConfig], Any]:
    """Factory creating the verify node handler."""
    from lyoko.application.use_cases.verify_incident import VerifyIncidentUseCase

    use_case = VerifyIncidentUseCase(
        mcp_client=mcp_client,
        llm=llm,
        supervisor=supervisor,
        approval_manager=approval_manager,
        chat_manager=chat_manager,
    )

    async def verify_node(state: dict[str, Any], config: RunnableConfig) -> dict[str, Any]:
        """Check, read-only, that the incident is actually resolved."""
        return await use_case.execute(state, config=config)

    return verify_node
