from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable

from lyoko.domain.models.chat import ApprovalRequest, ApprovalResponse, IncomingMessage

MessageHandler = Callable[[IncomingMessage], Awaitable[str | None]]
ApprovalHandler = Callable[[ApprovalResponse], Awaitable[None]]


class ChatConnector(ABC):
    @abstractmethod
    async def start(self) -> None:
        pass

    @abstractmethod
    async def stop(self) -> None:
        pass

    @abstractmethod
    async def send_message(
        self,
        chat_id: str,
        text: str,
        reply_to_message_id: str | int | None = None,
        parse_mode: str = "Markdown",
    ) -> None:
        pass

    @abstractmethod
    async def send_approval_request(self, request: ApprovalRequest) -> None:
        pass

    @abstractmethod
    def register_message_handler(self, handler: MessageHandler) -> None:
        pass

    @abstractmethod
    def register_approval_handler(self, handler: ApprovalHandler) -> None:
        pass
