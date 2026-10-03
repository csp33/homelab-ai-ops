"""Routing of operator messages: a plain conversation, or an incident to work through."""

import re
from enum import StrEnum

from lyoko.application.prompts.loader import load_prompt


class Route(StrEnum):
    CHAT = "chat"
    """Answer a question or carry out a request in one conversational run."""

    INCIDENT = "incident"
    """Investigate, fix, verify and report: the structured incident flow."""


ROUTER_SYSTEM_PROMPT = load_prompt("router.md")

_ROUTE_RE = re.compile(r"\b(CHAT|INCIDENT)\b", re.IGNORECASE)


def parse_route(answer: str) -> Route:
    """Read the router's one-word answer. Anything unclear falls back to ``Route.CHAT``.

    Chat is the safe default: it answers and acts through the same approval gate, whereas
    the incident flow would start an investigation nobody asked for.
    """
    match = _ROUTE_RE.search(answer or "")
    if match and match.group(1).upper() == "INCIDENT":
        return Route.INCIDENT
    return Route.CHAT
