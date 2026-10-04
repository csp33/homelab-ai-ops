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
    reply_to_message_id: int | str | None = Field(
        default=None, description="Optional message ID to reply directly to"
    )


class TelegramReactionRequest(BaseModel):
    chat_id: str | None = Field(
        default=None, description="Target chat ID, fallback to default if None"
    )
    message_id: int = Field(..., description="Message ID to set reaction on")
    emoji: str = Field(
        default="👀", description="Emoji to react with (e.g. '👀', '⚡', '👍', '🔥', '🎉')"
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
