"""Domain interface for Telegram client adapter."""

from abc import ABC, abstractmethod
from typing import Any

from homelab_mcp.domain.models.telegram import TelegramAlertRequest, TelegramMessageRequest


class TelegramClientInterface(ABC):
    @abstractmethod
    async def send_message(self, request: TelegramMessageRequest) -> dict[str, Any]:
        """Send a standard text message to Telegram."""
        pass

    @abstractmethod
    async def send_alert(self, request: TelegramAlertRequest) -> dict[str, Any]:
        """Send a formatted alert message with severity indicator to Telegram."""
        pass
