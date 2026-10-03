"""LYOKO Agent Application Composition Root."""

import asyncio
import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg_pool import AsyncConnectionPool

from lyoko.application.alert_guard import AlertStormProtector
from lyoko.application.chat_agent import InteractiveChatAgent
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
from lyoko.application.workflow import create_lyoko_graph
from lyoko.config import settings
from lyoko.domain.exceptions.mcp import MCPGatewayError
from lyoko.domain.interfaces.llm import LLMClientInterface
from lyoko.domain.interfaces.mcp import MCPClientInterface
from lyoko.infrastructure.chat.telegram import TelegramConnector
from lyoko.infrastructure.db.memory_repository import PostgresMemoryRepository
from lyoko.infrastructure.embeddings import EmbeddingsService
from lyoko.infrastructure.llm.openai import OpenAILLMAdapter
from lyoko.infrastructure.mcp.client import FastMCPClient
from lyoko.infrastructure.observability.langfuse import LangfuseTracer
from lyoko.infrastructure.web.controller import create_feedback_router, create_webhook_router


class HealthEndpointFilter(logging.Filter):
    """Filter out HTTP access log records for health check endpoints (/health, /healthz)."""

    def filter(self, record: logging.LogRecord) -> bool:
        if record.args and len(record.args) >= 3:
            path = record.args[2]
            if isinstance(path, str):
                clean_path = path.split("?")[0].rstrip("/")
                if clean_path in ("/health", "/healthz"):
                    return False
        msg = record.getMessage()
        return not (
            "GET /health" in msg
            or "GET /healthz" in msg
            or "HEAD /health" in msg
            or "HEAD /healthz" in msg
        )


logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logging.getLogger("uvicorn.access").addFilter(HealthEndpointFilter())
logger = logging.getLogger("lyoko")


def build_llm_adapter() -> LLMClientInterface | None:
    """Instantiate concrete LLM infrastructure adapter if configured."""
    if not settings.openai_api_key:
        return None

    api_key = (
        settings.openai_api_key.get_secret_value()
        if hasattr(settings.openai_api_key, "get_secret_value")
        else str(settings.openai_api_key)
    )
    return OpenAILLMAdapter(
        api_key=api_key,
        model_name=settings.openai_model,
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
        bot_token = (
            settings.telegram_bot_token.get_secret_value()
            if hasattr(settings.telegram_bot_token, "get_secret_value")
            else str(settings.telegram_bot_token)
        )
        telegram_connector = TelegramConnector(
            bot_token=bot_token,
            allowed_user_ids=settings.telegram_allowed_user_ids,
            allowed_chat_ids=settings.telegram_allowed_chat_ids,
            default_chat_id=settings.telegram_default_chat_id,
            memory_repository=memory_repo,
            embeddings_service=embeddings_service,
        )
        telegram_connector.register_approval_handler(approval_manager.resolve_approval)
        chat_manager.add_connector(telegram_connector)

    return chat_manager


def build_tracer() -> LangfuseTracer:
    """Instantiate the Langfuse tracer (a no-op without credentials)."""
    secret = settings.langfuse_secret_key
    secret_value = (
        secret.get_secret_value()
        if secret and hasattr(secret, "get_secret_value")
        else str(secret or "")
    )
    return LangfuseTracer(
        public_key=settings.langfuse_public_key or "",
        secret_key=secret_value,
        host=settings.langfuse_host,
        environment=settings.get_langfuse_environment(),
        release=settings.langfuse_release,
    )


def wire_chat_agent(app: FastAPI, chat_manager: ChatManager) -> None:
    """Send incoming chat messages to the graph stored in ``app.state.workflow_engine``."""
    chat_agent = InteractiveChatAgent(
        lambda: app.state.workflow_engine,
        tracer=getattr(app.state, "tracer", None),
        session_tracker=chat_manager.session_tracker,
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.getLogger("uvicorn.access").addFilter(HealthEndpointFilter())
    logger.info("Initializing LYOKO Auto-Remediation Agent...")
    db_uri = settings.get_postgres_uri()
    pool = None
    checkpointer = None
    memory_repo = None
    embeddings_service = EmbeddingsService()

    if db_uri:
        try:
            logger.info(
                f"Connecting to PostgreSQL checkpointer at {settings.postgres_host}:{settings.postgres_port}/{settings.postgres_db}..."
            )
            pool = AsyncConnectionPool(
                conninfo=db_uri,
                max_size=settings.postgres_pool_max_size,
                kwargs={"autocommit": True, "connect_timeout": 3},
                open=False,
                timeout=5.0,
            )
            await asyncio.wait_for(pool.open(), timeout=5.0)

            # Setup LangGraph checkpointer
            checkpointer = AsyncPostgresSaver(pool)
            await asyncio.wait_for(checkpointer.setup(), timeout=5.0)
            logger.info("PostgreSQL checkpointer initialized and tables ready.")

            # Setup Memory repository & run migrations
            memory_repo = PostgresMemoryRepository(pool)
            try:
                memory_repo.run_migrations()
            except Exception as exc:
                logger.warning(f"Alembic auto-migration warning: {exc}")

            logger.info("PostgreSQL memory repository initialized.")
        except Exception as exc:
            logger.error(f"Failed to initialize PostgreSQL components: {exc}", exc_info=True)
            if pool:
                await pool.close()
                pool = None
            checkpointer = None
            memory_repo = None
    else:
        logger.warning(
            "No PostgreSQL credentials configured. LYOKO running without persistent memory & checkpointer."
        )

    llm = getattr(app.state, "llm", None) or build_llm_adapter()
    mcp_client = getattr(app.state, "mcp_client", None) or FastMCPClient()
    approval_manager = getattr(app.state, "approval_manager", None) or ApprovalManager()
    try:
        await verify_mcp_gateway(mcp_client)
    except MCPGatewayError:
        if pool:
            await pool.close()
        raise
    chat_manager = build_chat_manager(
        approval_manager,
        memory_repo=memory_repo,
        embeddings_service=embeddings_service,
    )
    app.state.chat_manager = chat_manager
    wire_chat_agent(app, chat_manager)

    specialists = getattr(app.state, "specialists", None) or build_domain_specialists(
        mcp_client, llm
    )
    supervisor = getattr(app.state, "supervisor", None) or build_supervisor(specialists, llm)

    alert_guard = AlertStormProtector(chat_manager=chat_manager)
    app.state.alert_guard = alert_guard

    # Rebuilt now that the checkpointer exists. Everything reads the graph from app.state.
    workflow_engine = create_lyoko_graph(
        mcp_client,
        approval_manager=approval_manager,
        chat_manager=chat_manager,
        checkpointer=checkpointer,
        llm=llm,
        supervisor=supervisor,
        specialists=specialists,
        memory_repository=memory_repo,
        embeddings_service=embeddings_service,
    )

    app.state.llm = llm
    app.state.specialists = specialists
    app.state.supervisor = supervisor
    app.state.workflow_engine = workflow_engine
    app.state.db_pool = pool
    app.state.checkpointer = checkpointer
    app.state.memory_repository = memory_repo
    app.state.embeddings_service = embeddings_service

    await chat_manager.start_all()
    yield
    logger.info("Shutting down LYOKO Agent...")
    await chat_manager.stop_all()
    if pool:
        await pool.close()


def create_app() -> FastAPI:
    llm = build_llm_adapter()
    mcp_client = FastMCPClient()
    approval_manager = ApprovalManager()
    chat_manager = build_chat_manager(approval_manager)
    tracer = build_tracer()
    specialists = build_domain_specialists(mcp_client, llm)
    supervisor = build_supervisor(specialists, llm)
    alert_guard = AlertStormProtector(chat_manager=chat_manager)

    app = FastAPI(title="LYOKO Auto-Remediation Agent", lifespan=lifespan)

    # Initial graph (without persistent checkpointer until lifespan runs)
    workflow_engine = create_lyoko_graph(
        mcp_client,
        approval_manager=approval_manager,
        chat_manager=chat_manager,
        llm=llm,
        supervisor=supervisor,
        specialists=specialists,
    )
    app.state.llm = llm
    app.state.mcp_client = mcp_client
    app.state.specialists = specialists
    app.state.supervisor = supervisor
    app.state.approval_manager = approval_manager
    app.state.chat_manager = chat_manager
    app.state.alert_guard = alert_guard
    app.state.workflow_engine = workflow_engine
    app.state.tracer = tracer
    app.state.checkpointer = None
    app.state.db_pool = None
    app.state.memory_repository = None
    app.state.embeddings_service = None

    wire_chat_agent(app, chat_manager)

    # No engine is passed: the webhook reads app.state.workflow_engine on every request, so it
    # uses the graph rebuilt with the checkpointer in lifespan.
    app.include_router(create_webhook_router(tracer=tracer, alert_guard=alert_guard))

    feedback_router = create_feedback_router()
    app.include_router(feedback_router)

    @app.get("/healthz")
    @app.get("/health")
    async def health_check():
        has_db = getattr(app.state, "checkpointer", None) is not None
        has_memory = getattr(app.state, "memory_repository", None) is not None
        return {
            "status": "healthy",
            "service": "lyoko-agent",
            "postgres_checkpointer": has_db,
            "agent_memory": has_memory,
        }

    return app


app = create_app()


def main():
    logging.getLogger("uvicorn.access").addFilter(HealthEndpointFilter())
    logger.info(f"Starting LYOKO agent on {settings.lyoko_host}:{settings.lyoko_port}")
    uvicorn.run(app, host=settings.lyoko_host, port=settings.lyoko_port)


if __name__ == "__main__":
    main()
