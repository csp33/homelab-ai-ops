"""Concrete construction and wiring for LYOKO's composition root.

Instantiate infrastructure adapters, application services, and the graph, and wire the chat
connectors to the handlers that answer incoming messages.
"""

import logging

from fastapi import FastAPI

from lyoko.application.chat_agent import ChatHistoryTracker, InteractiveChatAgent
from lyoko.application.chat_manager import ChatManager
from lyoko.application.chat_sessions import ChatSessionTracker
from lyoko.application.hitl import ApprovalManager
from lyoko.application.specialists.agent import DomainSpecialistAgent
from lyoko.application.specialists.prompts import (
    K8S_SPECIALIST_PROMPT,
    NETWORK_SPECIALIST_PROMPT,
    OBSERVABILITY_SPECIALIST_PROMPT,
    SMARTHOME_SPECIALIST_PROMPT,
)
from lyoko.application.supervisor import SupervisorAgent
from lyoko.config import settings
from lyoko.domain.exceptions.mcp import MCPGatewayError
from lyoko.domain.interfaces.llm import LLMClientInterface
from lyoko.domain.interfaces.mcp import MCPClientInterface
from lyoko.infrastructure.chat.telegram import TelegramConnector
from lyoko.infrastructure.db.memory_repository import PostgresMemoryRepository
from lyoko.infrastructure.embeddings import EmbeddingsService
from lyoko.infrastructure.llm.openai import OpenAILLMAdapter
from lyoko.infrastructure.observability.langfuse import LangfuseTracer

logger = logging.getLogger("lyoko")


def _secret(value: object) -> str:
    """Return a secret's plain value, accepting pydantic ``SecretStr`` or raw strings."""
    if value and hasattr(value, "get_secret_value"):
        return value.get_secret_value()
    return str(value) if value else ""


def build_llm_adapter(
    model_name: str | None = None, use_responses_api: bool | None = None
) -> LLMClientInterface | None:
    """Instantiate concrete LLM infrastructure adapter if configured.

    ``model_name`` overrides the default model, which lets the composition root give one phase a
    stronger (or cheaper) model without affecting the others. ``use_responses_api`` overrides the
    OpenAI runtime for A/B comparisons; it defaults to the configured setting.
    """
    if not settings.openai_api_key:
        return None
    if use_responses_api is None:
        use_responses_api = settings.openai_use_responses_api
    return OpenAILLMAdapter(
        api_key=_secret(settings.openai_api_key),
        model_name=model_name or settings.openai_model,
        use_responses_api=use_responses_api,
    )


def build_domain_specialists(
    mcp_client: MCPClientInterface | None,
    llm: LLMClientInterface | None,
) -> dict[str, DomainSpecialistAgent]:
    """Instantiate domain specialist subagents."""
    return {
        "kubernetes": DomainSpecialistAgent(
            name="k8s_specialist",
            domain="kubernetes",
            system_prompt=K8S_SPECIALIST_PROMPT,
            llm=llm,
            mcp_client=mcp_client,
        ),
        "unifi": DomainSpecialistAgent(
            name="network_specialist",
            domain="unifi",
            system_prompt=NETWORK_SPECIALIST_PROMPT,
            llm=llm,
            mcp_client=mcp_client,
        ),
        "homeassistant": DomainSpecialistAgent(
            name="smarthome_specialist",
            domain="homeassistant",
            system_prompt=SMARTHOME_SPECIALIST_PROMPT,
            llm=llm,
            mcp_client=mcp_client,
        ),
        "grafana": DomainSpecialistAgent(
            name="observability_specialist",
            domain="grafana",
            system_prompt=OBSERVABILITY_SPECIALIST_PROMPT,
            llm=llm,
            mcp_client=mcp_client,
        ),
    }


def build_supervisor(
    specialists: dict[str, DomainSpecialistAgent],
    llm: LLMClientInterface | None,
) -> SupervisorAgent:
    """Instantiate central multi-agent supervisor."""
    return SupervisorAgent(specialists=specialists, llm=llm)


def build_chat_manager(
    approval_manager: ApprovalManager,
    memory_repo: PostgresMemoryRepository | None = None,
    embeddings_service: EmbeddingsService | None = None,
) -> ChatManager:
    """Instantiate the chat connectors.

    Incoming messages are wired in separately (see ``wire_chat_agent``), because the agent that
    answers them needs the graph, and the graph needs this manager to ask for approvals.
    """
    session_tracker = ChatSessionTracker(settings.chat_session_idle_timeout_seconds)
    chat_manager = ChatManager(session_tracker=session_tracker)

    if settings.telegram_enabled and settings.telegram_bot_token:
        logger.info("Configuring Telegram connector for private assistant & HITL alerts...")
        telegram_connector = TelegramConnector(
            bot_token=_secret(settings.telegram_bot_token),
            allowed_user_ids=settings.telegram_allowed_user_ids,
            allowed_chat_ids=settings.telegram_allowed_chat_ids,
            default_chat_id=settings.telegram_default_chat_id,
            discussion_group_id=settings.telegram_discussion_group_id,
            memory_repository=memory_repo,
            embeddings_service=embeddings_service,
        )
        telegram_connector.register_approval_handler(approval_manager.resolve_approval)
        chat_manager.add_connector(telegram_connector)

    return chat_manager


def build_tracer() -> LangfuseTracer:
    """Instantiate the Langfuse tracer (a no-op without credentials)."""
    return LangfuseTracer(
        public_key=settings.langfuse_public_key or "",
        secret_key=_secret(settings.langfuse_secret_key),
        host=settings.langfuse_host,
        environment=settings.get_langfuse_environment(),
        release=settings.langfuse_release,
    )


def wire_chat_agent(app: FastAPI, chat_manager: ChatManager) -> None:
    """Send incoming chat messages to the graph stored in ``app.state.workflow_engine``."""
    history_tracker = ChatHistoryTracker()
    chat_agent = InteractiveChatAgent(
        lambda: app.state.workflow_engine,
        tracer=getattr(app.state, "tracer", None),
        session_tracker=chat_manager.session_tracker,
        history_tracker=history_tracker,
    )
    chat_manager.register_message_handler(chat_agent.handle_message)


async def verify_mcp_gateway(mcp_client: MCPClientInterface) -> None:
    """Check the MCP gateway at startup so misconfiguration is loud instead of silent.

    Configuration errors (wrong URL, rejected credentials) abort startup when
    ``MCP_FAIL_FAST`` is enabled, because retrying cannot fix them and the agent would
    otherwise run without any tools. A gateway that is merely unreachable (e.g. still
    starting) is logged as an error but does not prevent the agent from booting.
    """
    try:
        await mcp_client.verify_connection()
    except MCPGatewayError as exc:
        logger.error("MCP gateway check failed: %s", exc)
        if exc.is_configuration_error and settings.mcp_fail_fast:
            raise
