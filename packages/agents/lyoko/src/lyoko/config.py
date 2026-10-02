"""Configuration settings for LYOKO agent."""

import json
from typing import Any
from urllib.parse import quote_plus

from pydantic import AliasChoices, Field, SecretStr, field_validator
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
    mcp_fail_fast: bool = Field(
        default=True,
        description=(
            "Abort startup when the MCP gateway rejects our credentials or the URL is not an "
            "MCP endpoint (HTTP 401/403/404). A merely unreachable gateway only logs an error."
        ),
    )

    # Telegram Bot settings
    telegram_enabled: bool = Field(
        default=False,
        description="Enable Telegram private assistant, channel, and HITL notifications",
    )
    telegram_bot_token: SecretStr | None = Field(
        default=None, description="Telegram Bot Token from @BotFather"
    )
    telegram_allowed_user_ids: list[str] | str = Field(
        default_factory=list,
        description="List of authorized Telegram user IDs allowed to interact with the bot",
    )
    telegram_allowed_chat_ids: list[str] | str = Field(
        default_factory=list,
        description="List of authorized Telegram channel or group chat IDs (e.g. -1001234567890)",
    )
    telegram_default_chat_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "telegram_default_chat_id", "telegram_chat_id", "telegram_channel_id"
        ),
        description="Default Telegram Chat/Channel ID for broadcast notifications and alerts",
    )

    # Guardrails
    max_remediation_retries: int = Field(
        default=2, description="Maximum automated remediation retry loops"
    )
    verification_delay_seconds: int = Field(
        default=10, description="Seconds to wait before verifying pod health"
    )

    # General Environment
    environment: str = Field(
        default="local",
        description="Deployment environment (e.g. 'local', 'homelab', 'development', 'production')",
    )

    # Observability (Langfuse / OpenTelemetry)
    langfuse_enabled: bool = Field(default=True, description="Enable Langfuse tracing")
    langfuse_public_key: str | None = Field(default=None, description="Langfuse Public Key")
    langfuse_secret_key: SecretStr | None = Field(default=None, description="Langfuse Secret Key")
    langfuse_host: str = Field(
        default="https://cloud.langfuse.com", description="Langfuse Host URL"
    )
    langfuse_environment: str | None = Field(
        default=None,
        description="Langfuse environment tag override (defaults to environment setting if not set)",
    )
    langfuse_release: str | None = Field(
        default=None,
        description="Release version identifier for Langfuse tracing",
    )

    chat_session_idle_timeout_seconds: int = Field(
        default=1800,
        ge=1,
        description=(
            "Seconds of chat inactivity after which a new Langfuse session is started "
            "for the next message in the same chat"
        ),
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

    @field_validator("telegram_allowed_user_ids", "telegram_allowed_chat_ids", mode="before")
    @classmethod
    def parse_allowed_ids(cls, v: Any) -> list[str]:
        if isinstance(v, (int, float)):
            return [str(v)]
        if isinstance(v, str):
            v = v.strip()
            if v.startswith("[") and v.endswith("]"):
                try:
                    return [str(x) for x in json.loads(v)]
                except Exception:
                    pass
            return [item.strip() for item in v.split(",") if item.strip()]
        if isinstance(v, (list, tuple, set)):
            return [str(x) for x in v]
        return v or []

    def get_langfuse_environment(self) -> str:
        """Return the effective Langfuse environment string."""
        return self.langfuse_environment or self.environment

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
