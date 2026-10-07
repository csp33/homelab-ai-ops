"""Dispatcher node evaluating registered deterministic triage handlers."""

import logging
from collections.abc import Callable, Sequence
from typing import Any

from langchain_core.runnables import RunnableConfig
from lyoko.application.triage.base import TriageHandler

logger = logging.getLogger("lyoko.workflow.triage")

TRIAGE_DIAGNOSE = "diagnose"
TRIAGE_HANDLED = "handled"


def choose_triage(state: dict[str, Any]) -> str:
    """Route a handled fast-path incident to notify, otherwise continue to diagnose."""
    return TRIAGE_HANDLED if state.get("triage") == TRIAGE_HANDLED else TRIAGE_DIAGNOSE


def create_triage_node(
    handlers: Sequence[TriageHandler],
) -> Callable[[dict[str, Any], RunnableConfig], Any]:
    """Factory creating the composite triage node delegating to registered handlers."""

    async def triage_node(state: dict[str, Any], config: RunnableConfig) -> dict[str, Any]:
        for handler in handlers:
            try:
                if handler.can_handle(state):
                    result = await handler.execute(state, config)
                    if result is not None and result.handled:
                        return result.to_state_patch()
            except Exception as exc:
                logger.warning(
                    "Triage handler %s failed: %s; falling through.",
                    handler.__class__.__name__,
                    exc,
                )
        return {"triage": TRIAGE_DIAGNOSE}

    return triage_node
