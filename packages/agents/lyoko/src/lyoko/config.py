"""Configuration settings for LYOKO agent."""

from urllib.parse import quote_plus

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
        default="http://localhost:8000/mcp", description="homelab-mcp Streamable HTTP URL"
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

    # PostgreSQL Checkpointer (Persistent LangGraph state)
    postgres_uri: str | None = Field(
        default=None,
        description="Full PostgreSQL connection URI (e.g., postgresql://user:pass@host:5432/dbname)",
    )
    postgres_host: str = Field(
        default="postgresql-rw.postgresql-cnpg.svc.cluster.local",
        description="PostgreSQL hostname",
    )
    postgres_port: int = Field(default=5432, description="PostgreSQL port")
    postgres_user: str = Field(default="lyoko", description="PostgreSQL username")
    postgres_password: str = Field(default="", description="PostgreSQL password")
    postgres_db: str = Field(default="lyoko", description="PostgreSQL database name")
    postgres_pool_max_size: int = Field(
        default=20, description="PostgreSQL connection pool max size"
    )

    def get_postgres_uri(self) -> str | None:
        """Construct PostgreSQL connection URI if configured."""
        if self.postgres_uri:
            return self.postgres_uri
        if self.postgres_password:
            user = quote_plus(self.postgres_user)
            password = quote_plus(self.postgres_password)
            return (
                f"postgresql://{user}:{password}"
                f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
            )
        return None


settings = AgentSettings()
