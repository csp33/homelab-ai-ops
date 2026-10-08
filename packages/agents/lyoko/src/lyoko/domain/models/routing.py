"""Domain models for event routing."""

from enum import StrEnum


class Route(StrEnum):
    CHAT = "chat"
    """Answer a question or carry out a request in one conversational run."""

    INCIDENT = "incident"
    """Investigate, fix, verify and report: the structured incident flow."""
