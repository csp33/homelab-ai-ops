"""Use case for routing incoming events into either the chat branch or incident branch."""

import logging
from typing import Any

from langchain_core.runnables import RunnableConfig
from lyoko.application.nodes.helpers import is_message
from lyoko.application.router import ROUTER_SYSTEM_PROMPT, Route, parse_route
from lyoko.domain.interfaces.llm import LLMClientInterface

logger = logging.getLogger("lyoko.application.use_cases.route_event")


class RouteEventUseCase:
    """Evaluates whether an incoming event represents an incident or a chat interaction."""

    def __init__(self, llm: LLMClientInterface | None = None) -> None:
        self.llm = llm

    async def execute(
        self, state: dict[str, Any], config: RunnableConfig | None = None
    ) -> dict[str, Any]:
        """Alerts are always incidents. Messages are classified via LLM into CHAT or INCIDENT."""
        if not is_message(state):
            return {"route": Route.INCIDENT.value}

        text = state.get("text", "")
        if self.llm is None:
            return {"route": Route.CHAT.value}

        history_context = state.get("history_context", "")
        router_input = text if not history_context else f"{text}{history_context}"

        try:
            answer = await self.llm.chat(
                prompt=router_input,
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
