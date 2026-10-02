import logging

from lyoko.domain.interfaces.chat_connector import ChatConnector
from lyoko.domain.models.chat import ApprovalRequest

logger = logging.getLogger("lyoko.application.chat_manager")


class ChatManager:
    """Manages active chat connectors and orchestrates broadcast messaging."""

    def __init__(self, connectors: list[ChatConnector] | None = None) -> None:
        self.connectors: list[ChatConnector] = connectors if connectors is not None else []

    def add_connector(self, connector: ChatConnector) -> None:
        """Register an additional ChatConnector instance."""
        self.connectors.append(connector)

    async def start_all(self) -> None:
        """Start all registered chat connectors."""
        for conn in self.connectors:
            await conn.start()

    async def stop_all(self) -> None:
        """Stop all registered chat connectors."""
        for conn in self.connectors:
            await conn.stop()

    async def broadcast_message(
        self, chat_id: str, text: str, parse_mode: str = "Markdown"
    ) -> None:
        """Send message across all registered connectors with fault tolerance."""
        for conn in self.connectors:
            try:
                await conn.send_message(chat_id=chat_id, text=text, parse_mode=parse_mode)
            except Exception as e:
                logger.error("Error broadcasting message via connector: %s", e)

    async def broadcast_approval_request(self, request: ApprovalRequest) -> None:
        """Send approval request across all registered connectors with fault tolerance."""
        for conn in self.connectors:
            try:
                await conn.send_approval_request(request)
            except Exception as e:
                logger.error("Error broadcasting approval request via connector: %s", e)
