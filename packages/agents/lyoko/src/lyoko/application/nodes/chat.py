"""Chat branch node answering operator queries with tool-gate safety and semantic memory."""

import logging
from collections.abc import Callable
from typing import Any

from langchain_core.runnables import RunnableConfig
from lyoko.application.use_cases.handle_chat import HandleChatTurnUseCase
from lyoko.domain.interfaces.approval import ApprovalManagerInterface
from lyoko.domain.interfaces.chat_service import ChatServiceInterface
from lyoko.domain.interfaces.embeddings import EmbeddingsServiceInterface
from lyoko.domain.interfaces.llm import LLMClientInterface
from lyoko.domain.interfaces.mcp import MCPClientInterface
from lyoko.domain.interfaces.memory import MemoryRepositoryInterface
from lyoko.domain.interfaces.supervisor import SupervisorInterface

logger = logging.getLogger("lyoko.workflow.chat")


def create_chat_node(
    mcp_client: MCPClientInterface | None,
    llm: LLMClientInterface | None,
    supervisor: SupervisorInterface | None = None,
    approval_manager: ApprovalManagerInterface | None = None,
    chat_manager: ChatServiceInterface | None = None,
    memory_repository: MemoryRepositoryInterface | None = None,
    embeddings_service: EmbeddingsServiceInterface | None = None,
) -> Callable[[dict[str, Any], RunnableConfig], Any]:
    """Factory creating the chat node handler with injected dependencies."""

    use_case = HandleChatTurnUseCase(
        mcp_client=mcp_client,
        llm=llm,
        supervisor=supervisor,
        approval_manager=approval_manager,
        chat_manager=chat_manager,
        memory_repository=memory_repository,
        embeddings_service=embeddings_service,
    )

    async def chat_node(state: dict[str, Any], config: RunnableConfig) -> dict[str, Any]:
        """Answer the operator. Coordinates through the multi-agent supervisor with ToolGate safety."""
        return await use_case.execute(state, config=config)

    return chat_node
