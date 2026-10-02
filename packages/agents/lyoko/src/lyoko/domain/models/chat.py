from typing import Literal

from pydantic import BaseModel, Field


class ChatUser(BaseModel):
    user_id: str
    username: str | None = None
    first_name: str | None = None


class IncomingMessage(BaseModel):
    message_id: str
    chat_id: str
    user: ChatUser
    text: str
    reply_to_message_id: str | None = None


class SentMessage(BaseModel):
    """Reference to a message delivered by a chat connector."""

    chat_id: str
    message_id: str


class ApprovalAction(BaseModel):
    action_id: str
    label: str
    style: Literal["primary", "danger", "default"] = "default"


class ApprovalRequest(BaseModel):
    incident_id: str
    title: str
    details: str
    chat_id: str
    actions: list[ApprovalAction] = Field(default_factory=list)
    session_id: str | None = None


class ApprovalResponse(BaseModel):
    incident_id: str
    approved: bool
    user_id: str
    action_id: str = "approve"
    reason: str = ""
