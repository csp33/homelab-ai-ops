"""Domain models for Telegram notifications and alerts."""

from enum import StrEnum

from pydantic import BaseModel, Field


class TelegramSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"
    OK = "ok"


class TelegramMessageRequest(BaseModel):
    text: str = Field(..., description="Message text to send")
    chat_id: str | None = Field(
        default=None, description="Target chat ID, fallback to default if None"
    )
    parse_mode: str = Field(
        default="Markdown", description="Message parse mode (e.g. Markdown, HTML)"
    )


class TelegramAlertRequest(BaseModel):
    title: str = Field(..., description="Alert title")
    message: str = Field(..., description="Alert message body")
    severity: TelegramSeverity = Field(
        default=TelegramSeverity.WARNING, description="Alert severity level"
    )
    chat_id: str | None = Field(
        default=None, description="Target chat ID, fallback to default if None"
    )
