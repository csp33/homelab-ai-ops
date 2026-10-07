"""Chat branch node answering operator queries with tool-gate safety and semantic memory."""

import logging
from collections.abc import Callable
from typing import Any

from langchain_core.runnables import RunnableConfig
from lyoko.application.chat_manager import ChatManager
from lyoko.application.hitl import ApprovalManager
from lyoko.domain.interfaces.embeddings import EmbeddingsServiceInterface
from lyoko.domain.interfaces.llm import LLMClientInterface
from lyoko.domain.interfaces.memory import MemoryRepositoryInterface

logger = logging.getLogger("lyoko.workflow.chat")


def create_chat_node(
    mcp_client: Any,
    llm: LLMClientInterface | None,
    supervisor: Any = None,
    approval_manager: ApprovalManager | None = None,
    chat_manager: ChatManager | None = None,
    memory_repository: MemoryRepositoryInterface | None = None,
    embeddings_service: EmbeddingsServiceInterface | None = None,
) -> Callable[[dict[str, Any], RunnableConfig], Any]:
    """Factory creating the chat node handler with injected dependencies."""
    from lyoko.application.use_cases.handle_chat import HandleChatTurnUseCase

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
