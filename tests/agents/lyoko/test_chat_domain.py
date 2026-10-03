import pytest
from lyoko.domain.interfaces.chat_connector import (
    ApprovalHandler,
    ChatConnector,
    MessageHandler,
)
from lyoko.domain.models.chat import (
    ApprovalAction,
    ApprovalRequest,
    ApprovalResponse,
    ChatUser,
    IncomingMessage,
)


def test_chat_user_model():
    user = ChatUser(user_id="12345", username="admin", first_name="Admin")
    assert user.user_id == "12345"
    assert user.username == "admin"
    assert user.first_name == "Admin"


def test_chat_user_optional_fields():
    user = ChatUser(user_id="999")
    assert user.user_id == "999"
    assert user.username is None
    assert user.first_name is None


def test_incoming_message_model():
    user = ChatUser(user_id="101")
    msg = IncomingMessage(
        message_id="msg-1",
        chat_id="chat-100",
        user=user,
        text="/status",
    )
    assert msg.message_id == "msg-1"
    assert msg.chat_id == "chat-100"
    assert msg.user.user_id == "101"
    assert msg.text == "/status"


def test_approval_action_model():
    action_default = ApprovalAction(action_id="approve", label="Approve")
    assert action_default.action_id == "approve"
    assert action_default.label == "Approve"
    assert action_default.style == "default"

    action_danger = ApprovalAction(action_id="deny", label="Deny", style="danger")
    assert action_danger.style == "danger"


def test_approval_request_model():
    actions = [
        ApprovalAction(action_id="approve", label="Approve", style="primary"),
        ApprovalAction(action_id="deny", label="Deny", style="danger"),
    ]
    req = ApprovalRequest(
        incident_id="inc-oom-1",
        title="OOMKilled Incident",
        details="Pod crashed with OOMKilled",
        chat_id="chat-100",
        actions=actions,
    )
    assert req.incident_id == "inc-oom-1"
    assert len(req.actions) == 2
    assert req.actions[0].action_id == "approve"


def test_approval_response_model():
    res = ApprovalResponse(
        incident_id="inc-oom-1",
        approved=True,
        user_id="user-123",
    )
    assert res.incident_id == "inc-oom-1"
    assert res.approved is True
    assert res.user_id == "user-123"
    assert res.action_id == "approve"
    assert res.reason == ""


def test_chat_connector_abstract_class():
    with pytest.raises(TypeError):
        ChatConnector()  # type: ignore[abstract]


@pytest.mark.asyncio
async def test_concrete_chat_connector_implementation():
    class DummyChatConnector(ChatConnector):
        def __init__(self):
            self.started = False
            self.stopped = False
            self.sent_messages = []
            self.approval_requests = []
            self.msg_handler = None
            self.approval_handler = None

        async def start(self) -> None:
            self.started = True

        async def stop(self) -> None:
            self.stopped = True

        async def send_message(self, chat_id: str, text: str, parse_mode: str = "Markdown") -> None:
            self.sent_messages.append((chat_id, text, parse_mode))

        async def edit_message(
            self, chat_id: str, message_id: str | int, text: str, parse_mode: str = "Markdown"
        ) -> None:
            self.sent_messages.append((chat_id, text, parse_mode))

        async def send_approval_request(self, request: ApprovalRequest) -> None:
            self.approval_requests.append(request)

        def register_message_handler(self, handler: MessageHandler) -> None:
            self.msg_handler = handler

        def register_approval_handler(self, handler: ApprovalHandler) -> None:
            self.approval_handler = handler

    connector = DummyChatConnector()
    await connector.start()
    assert connector.started is True

    await connector.send_message("chat-1", "hello")
    assert connector.sent_messages == [("chat-1", "hello", "Markdown")]

    req = ApprovalRequest(
        incident_id="inc-1",
        title="Test",
        details="Detail",
        chat_id="chat-1",
    )
    await connector.send_approval_request(req)
    assert connector.approval_requests == [req]

    async def dummy_msg_handler(msg: IncomingMessage) -> str | None:
        return f"Echo: {msg.text}"

    async def dummy_appr_handler(appr: ApprovalResponse) -> None:
        pass

    connector.register_message_handler(dummy_msg_handler)
    connector.register_approval_handler(dummy_appr_handler)
    assert connector.msg_handler is dummy_msg_handler
    assert connector.approval_handler is dummy_appr_handler

    await connector.stop()
    assert connector.stopped is True
