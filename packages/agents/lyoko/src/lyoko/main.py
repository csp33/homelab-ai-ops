"""LYOKO Agent Application Composition Root."""

import asyncio
import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg_pool import AsyncConnectionPool

from lyoko.application.workflow import create_remediation_workflow
from lyoko.config import settings
from lyoko.infrastructure.mcp.client import FastMCPClient
from lyoko.infrastructure.observability.langfuse import LangfuseTracer
from lyoko.infrastructure.web.controller import create_webhook_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("lyoko")


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
                kwargs={"autocommit": True},
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

    mcp_client = FastMCPClient()
    workflow_engine = create_remediation_workflow(mcp_client, checkpointer=checkpointer)

    app.state.workflow_engine = workflow_engine
    app.state.db_pool = pool
    app.state.checkpointer = checkpointer

    yield

    logger.info("Shutting down LYOKO Agent...")
    if pool:
        await pool.close()


def create_app() -> FastAPI:
    app = FastAPI(title="LYOKO Auto-Remediation Agent", lifespan=lifespan)

    mcp_client = FastMCPClient()
    tracer = LangfuseTracer(
        public_key=settings.langfuse_public_key,
        secret_key=settings.langfuse_secret_key,
        host=settings.langfuse_host,
    )
    workflow_engine = create_remediation_workflow(mcp_client)

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
