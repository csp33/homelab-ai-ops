"""Multi-Agent Supervisor and Cross-Domain Orchestrator for LYOKO."""

import logging
from typing import Any

from lyoko.application.prompts.loader import load_prompt
from lyoko.domain.interfaces.llm import LLMClientInterface

logger = logging.getLogger("lyoko.supervisor")

SUPERVISOR_SYSTEM_PROMPT = load_prompt("supervisor.md")


class SupervisorAgent:
    """Orchestrates domain specialist subagents and plans multi-step cross-domain tasks."""

    def __init__(
        self,
        specialists: dict[str, Any] | None = None,
        llm: LLMClientInterface | None = None,
    ) -> None:
        self.specialists = specialists or {}
        self.llm = llm

    def get_specialist(self, domain: str) -> Any | None:
        """Retrieve a specialist by domain name."""
        return self.specialists.get(domain)

    async def delegate(
        self,
        domain: str,
        prompt: str,
        session_id: str | None = None,
        user_id: str | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Delegate a task directly to a specific domain specialist."""
        specialist = self.get_specialist(domain)
        if specialist is None:
            return f"Supervisor: No specialist registered for domain '{domain}'."
        logger.info("Supervisor delegating to %s specialist: %s", domain, prompt)
        return await specialist.run(
            prompt=prompt,
            session_id=session_id,
            user_id=user_id,
            tags=tags,
            metadata=metadata,
        )

    async def coordinate(
        self,
        prompt: str,
        session_id: str | None = None,
        user_id: str | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Coordinate multi-agent task execution."""
        logger.info("Supervisor coordinating request: %s", prompt)
        if self.llm is None:
            return f"Supervisor: LLM client not configured to process '{prompt}'."

        supervisor_tags = list(tags or [])
        supervisor_tags.extend(["supervisor", "multi-agent"])

        return await self.llm.chat(
            prompt=prompt,
            system_prompt=SUPERVISOR_SYSTEM_PROMPT,
            session_id=session_id,
            user_id=user_id,
            trace_name="supervisor-coordination",
            tags=supervisor_tags,
            metadata=metadata or {},
        )
