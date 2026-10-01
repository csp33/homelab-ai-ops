"""Configuration settings for LYOKO agent."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AgentSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Agent Server settings
    lyoko_host: str = Field(default="0.0.0.0", description="Host to bind FastAPI server")
    lyoko_port: int = Field(default=9000, description="Port for FastAPI webhook receiver")

    # LLM Provider
    openai_api_key: str = Field(default="", description="OpenAI API Key")
    openai_model: str = Field(default="gpt-4o-mini", description="OpenAI Model name")

    # MCP Gateway connection
    mcp_server_url: str = Field(
        default="http://localhost:8000/sse", description="homelab-mcp SSE URL"
    )
    service_token: str = Field(
        default="", description="Bearer token to authenticate against homelab-mcp"
    )

    # Guardrails
    max_remediation_retries: int = Field(
        default=2, description="Maximum automated remediation retry loops"
    )
    verification_delay_seconds: int = Field(
        default=10, description="Seconds to wait before verifying pod health"
    )

    # Observability (Langfuse / OpenTelemetry)
    langfuse_public_key: str = Field(default="", description="Langfuse Public Key")
    langfuse_secret_key: str = Field(default="", description="Langfuse Secret Key")
    langfuse_host: str = Field(
        default="https://cloud.langfuse.com", description="Langfuse Host URL"
    )


settings = AgentSettings()
