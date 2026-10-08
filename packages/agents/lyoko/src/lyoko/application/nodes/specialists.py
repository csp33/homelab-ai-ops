"""Domain specialist graph nodes for LYOKO StateGraph workflow."""

import logging
from collections.abc import Callable
from typing import Any

from langchain_core.runnables import RunnableConfig
from lyoko.application.chat_manager import ChatManager
from lyoko.application.hitl import ApprovalManager
from lyoko.application.use_cases.execute_specialist_task import ExecuteSpecialistTaskUseCase

logger = logging.getLogger("lyoko.workflow.specialist")


def create_specialist_node(
    domain: str,
    specialist: Any,
    mcp_client: Any = None,
    approval_manager: ApprovalManager | None = None,
    chat_manager: ChatManager | None = None,
) -> Callable[[dict[str, Any], RunnableConfig], Any]:
    """Factory creating an inline graph node for a specific domain specialist."""
    use_case = ExecuteSpecialistTaskUseCase(
        domain=domain,
        specialist=specialist,
        mcp_client=mcp_client,
        approval_manager=approval_manager,
        chat_manager=chat_manager,
    )

    async def specialist_node(state: dict[str, Any], config: RunnableConfig) -> dict[str, Any]:
        """Thin adapter delegating execution to ExecuteSpecialistTaskUseCase."""
        return await use_case.execute(state, config=config)

    return specialist_node
