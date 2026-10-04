"""In-process upstream provider exposing the Telegram bot as a gateway domain.

Unlike the other upstreams, Telegram is not a separate MCP sub-process: it is a built-in
capability of the gateway. Registering it behind the same ``UpstreamMCPInterface`` makes its
tools part of the aggregated catalog, so they appear through ``gateway_get_domain_tools`` and
run through the single ``gateway_call_tool`` choke point (guardrails + audit).
"""

import logging
from typing import Any

from sector5_mcp.domain.interfaces.telegram import TelegramClientInterface
from sector5_mcp.domain.interfaces.upstream import UpstreamMCPInterface
from sector5_mcp.domain.models.telegram import (
    TelegramAlertRequest,
    TelegramMessageRequest,
    TelegramReactionRequest,
    TelegramSeverity,
)
from sector5_mcp.domain.models.upstream import ToolDefinition, ToolResult, UpstreamType

logger = logging.getLogger("sector5_mcp.upstream_telegram")

_OBJECT_SCHEMA: dict[str, Any] = {"type": "object", "properties": {}}


def _schema(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": required}


class TelegramUpstreamClient(UpstreamMCPInterface):
    """In-process provider wrapping a ``TelegramClientInterface`` as a gateway domain."""

    def __init__(self, client: TelegramClientInterface):
        self.client = client

    async def list_tools(self) -> list[ToolDefinition]:
        """Expose the Telegram actions as domain tools with their argument schemas."""
        return [
            ToolDefinition(
                name="telegram_send_message",
                description="Send a text message to Telegram.",
                parameters=_schema(
                    {
                        "text": {"type": "string", "description": "Message text to send"},
                        "chat_id": {
                            "type": "string",
                            "description": "Target chat ID (falls back to default if omitted)",
                        },
                        "parse_mode": {
                            "type": "string",
                            "description": "Text parsing mode (e.g. 'Markdown', 'HTML')",
                        },
                        "reply_to_message_id": {
                            "type": "integer",
                            "description": "Optional message ID to reply to directly",
                        },
                    },
                    ["text"],
                ),
                upstream_type=UpstreamType.TELEGRAM,
            ),
            ToolDefinition(
                name="telegram_send_alert",
                description="Send a formatted alert message with severity indicator to Telegram.",
                parameters=_schema(
                    {
                        "title": {"type": "string", "description": "Alert title"},
                        "message": {"type": "string", "description": "Alert message body"},
                        "severity": {
                            "type": "string",
                            "enum": [s.value for s in TelegramSeverity],
                            "description": "Alert severity level",
                        },
                        "chat_id": {
                            "type": "string",
                            "description": "Target chat ID (falls back to default if omitted)",
                        },
                    },
                    ["title", "message"],
                ),
                upstream_type=UpstreamType.TELEGRAM,
            ),
            ToolDefinition(
                name="telegram_set_reaction",
                description="Set an emoji reaction on a Telegram message.",
                parameters=_schema(
                    {
                        "message_id": {"type": "integer", "description": "Message ID to react to"},
                        "emoji": {"type": "string", "description": "Emoji to react with"},
                        "chat_id": {
                            "type": "string",
                            "description": "Target chat ID (falls back to default if omitted)",
                        },
                    },
                    ["message_id"],
                ),
                upstream_type=UpstreamType.TELEGRAM,
            ),
        ]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        """Dispatch a Telegram domain tool to the in-process client."""
        if name == "telegram_send_message":
            request = TelegramMessageRequest(**arguments)
            result = await self.client.send_message(request)
        elif name == "telegram_send_alert":
            result = await self.client.send_alert(self._alert_request(arguments))
        elif name == "telegram_set_reaction":
            request = TelegramReactionRequest(**arguments)
            result = await self.client.set_reaction(request)
        else:
            return ToolResult(
                status="error",
                content=f"Unknown telegram tool '{name}'.",
                is_error=True,
            )
        return ToolResult(status="success", content=result)

    @staticmethod
    def _alert_request(arguments: dict[str, Any]) -> TelegramAlertRequest:
        raw_severity = arguments.get("severity")
        try:
            severity = TelegramSeverity(str(raw_severity).lower())
        except ValueError:
            severity = TelegramSeverity.WARNING
        return TelegramAlertRequest(
            title=arguments["title"],
            message=arguments["message"],
            severity=severity,
            chat_id=arguments.get("chat_id"),
        )
