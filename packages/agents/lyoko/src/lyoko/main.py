"""LYOKO Agent Application Composition Root."""

import asyncio
import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg_pool import AsyncConnectionPool

from lyoko.application.chat_agent import InteractiveChatAgent
from lyoko.application.chat_manager import ChatManager
from lyoko.application.hitl import ApprovalManager
from lyoko.application.workflow import create_remediation_workflow
from lyoko.config import settings
from lyoko.domain.interfaces.llm import LLMClientInterface
from lyoko.infrastructure.chat.telegram import TelegramConnector
from lyoko.infrastructure.llm.openai import OpenAILLMAdapter
from lyoko.infrastructure.mcp.client import FastMCPClient
from lyoko.infrastructure.observability.langfuse import LangfuseTracer
from lyoko.infrastructure.web.controller import create_webhook_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
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


def build_chat_manager(
    mcp_client: FastMCPClient,
    approval_manager: ApprovalManager,
    llm: LLMClientInterface | None = None,
) -> ChatManager:
    """Instantiate and configure active chat connectors."""
    chat_manager = ChatManager()

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
        )
        chat_agent = InteractiveChatAgent(mcp_client=mcp_client, llm=llm)
        telegram_connector.register_message_handler(chat_agent.handle_message)
        telegram_connector.register_approval_handler(approval_manager.resolve_approval)
        chat_manager.add_connector(telegram_connector)

    return chat_manager


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing LYOKO Auto-Remediation Agent...")
    db_uri = settings.get_postgres_uri()
    pool = None
    checkpointer = None

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
            checkpointer = AsyncPostgresSaver(pool)
            await asyncio.wait_for(checkpointer.setup(), timeout=5.0)
            logger.info("PostgreSQL checkpointer initialized and tables ready.")
        except Exception as exc:
            logger.error(f"Failed to initialize PostgreSQL checkpointer: {exc}", exc_info=True)
            if pool:
                await pool.close()
                pool = None
            checkpointer = None
    else:
        logger.warning(
            "No PostgreSQL credentials configured. LYOKO running without persistent checkpointer."
        )

    llm = getattr(app.state, "llm", None) or build_llm_adapter()
    mcp_client = getattr(app.state, "mcp_client", None) or FastMCPClient()
    approval_manager = getattr(app.state, "approval_manager", None) or ApprovalManager()
    chat_manager = getattr(app.state, "chat_manager", None) or build_chat_manager(
        mcp_client, approval_manager, llm=llm
    )

    workflow_engine = create_remediation_workflow(
        mcp_client,
        approval_manager=approval_manager,
        chat_manager=chat_manager,
        checkpointer=checkpointer,
        llm=llm,
    )

    app.state.llm = llm
    app.state.workflow_engine = workflow_engine
    app.state.db_pool = pool
    app.state.checkpointer = checkpointer

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
    chat_manager = build_chat_manager(mcp_client, approval_manager, llm=llm)

    secret_val = ""
    if settings.langfuse_secret_key:
        secret_val = (
            settings.langfuse_secret_key.get_secret_value()
            if hasattr(settings.langfuse_secret_key, "get_secret_value")
            else str(settings.langfuse_secret_key)
        )

    tracer = LangfuseTracer(
        public_key=settings.langfuse_public_key or "",
        secret_key=secret_val,
        host=settings.langfuse_host,
    )

    app = FastAPI(title="LYOKO Auto-Remediation Agent", lifespan=lifespan)

    # Initial workflow engine (without persistent checkpointer until lifespan runs)
    workflow_engine = create_remediation_workflow(
        mcp_client,
        approval_manager=approval_manager,
        chat_manager=chat_manager,
        llm=llm,
    )
    app.state.llm = llm
    app.state.mcp_client = mcp_client
    app.state.approval_manager = approval_manager
    app.state.chat_manager = chat_manager
    app.state.workflow_engine = workflow_engine
    app.state.tracer = tracer
    app.state.checkpointer = None
    app.state.db_pool = None

    webhook_router = create_webhook_router(workflow_engine, tracer=tracer)
    app.include_router(webhook_router)

    @app.get("/healthz")
    async def health_check():
        has_db = getattr(app.state, "checkpointer", None) is not None
        return {"status": "healthy", "service": "lyoko-agent", "postgres_checkpointer": has_db}

    return app


app = create_app()


def main():
    logger.info(f"Starting LYOKO agent on {settings.lyoko_host}:{settings.lyoko_port}")
    uvicorn.run(app, host=settings.lyoko_host, port=settings.lyoko_port)


if __name__ == "__main__":
    main()
