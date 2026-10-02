"""Routing of operator messages: a plain conversation, or an incident to work through."""

import re
from enum import StrEnum


class Route(StrEnum):
    CHAT = "chat"
    """Answer a question or carry out a request in one conversational run."""

    INCIDENT = "incident"
    """Investigate, fix, verify and report: the structured incident flow."""


ROUTER_SYSTEM_PROMPT = """You route messages that the homelab operator sends to LYOKO, an AI \
assistant that operates their homelab (Kubernetes, network, smart home, observability).

Reply with exactly one word.

INCIDENT: the operator reports that something is broken, degraded, down, failing or behaving \
wrongly, and wants it investigated or fixed. Example: "radarr keeps crashing, fix it", \
"the living room lights stopped responding", "the NAS is unreachable since this morning".

CHAT: everything else. Questions about the current state ("what IP does the printer have?"), \
requests to look something up, and direct instructions for one specific action ("scale sonarr \
to 2 replicas", "reload the Hue integration").

When in doubt, reply CHAT."""

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
