"""LYOKO Agent Application Composition Root."""

import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

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
    yield
    logger.info("Shutting down LYOKO Agent...")


def create_app() -> FastAPI:
    app = FastAPI(title="LYOKO Auto-Remediation Agent", lifespan=lifespan)

    # Assemble Clean Architecture Components
    mcp_client = FastMCPClient()
    tracer = LangfuseTracer(
        public_key=settings.langfuse_public_key,
        secret_key=settings.langfuse_secret_key,
        host=settings.langfuse_host,
    )
    workflow_engine = create_remediation_workflow(mcp_client)
    webhook_router = create_webhook_router(workflow_engine, tracer=tracer)

    app.include_router(webhook_router)

    @app.get("/healthz")
    async def health_check():
        return {"status": "healthy", "service": "lyoko-agent"}

    return app


app = create_app()


def main():
    logger.info(f"Starting LYOKO agent on {settings.lyoko_host}:{settings.lyoko_port}")
    uvicorn.run(app, host=settings.lyoko_host, port=settings.lyoko_port)


if __name__ == "__main__":
    main()
