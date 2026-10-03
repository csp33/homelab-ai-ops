"""Routing node for deciding whether an incoming event is a chat message or an incident."""

import logging
from collections.abc import Callable
from typing import Any

from langchain_core.runnables import RunnableConfig
from lyoko.application.nodes.helpers import is_message
from lyoko.application.router import ROUTER_SYSTEM_PROMPT, Route, parse_route
from lyoko.domain.interfaces.llm import LLMClientInterface

logger = logging.getLogger("lyoko.workflow.router")


def choose_branch(state: dict[str, Any]) -> str:
    """Determine downstream graph branch from routing state."""
    return "diagnose" if state.get("route") == Route.INCIDENT.value else "chat"


def create_route_node(
    llm: LLMClientInterface | None,
) -> Callable[[dict[str, Any], RunnableConfig], Any]:
    """Factory creating the route node handler with injected LLM client."""

    async def route_node(state: dict[str, Any], config: RunnableConfig) -> dict[str, Any]:
        """Alerts are incidents. For a message, the LLM decides between chat and incident."""
        if not is_message(state):
            return {"route": Route.INCIDENT.value}
        if llm is None:
            return {"route": Route.CHAT.value}

        try:
            answer = await llm.chat(
                prompt=state.get("text", ""),
                system_prompt=ROUTER_SYSTEM_PROMPT,
                trace_name="route-llm",
                tags=["phase:route"],
                parent_config=config,
            )
        except Exception as exc:
            logger.warning("Routing failed, answering in chat: %s", exc)
            return {"route": Route.CHAT.value}

        route = parse_route(answer)
        logger.info("Routed message to %s", route.value)
        return {"route": route.value}

    return route_node
