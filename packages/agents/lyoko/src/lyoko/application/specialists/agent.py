"""Domain specialist agent implementation for LYOKO."""

import logging
from typing import Any

from lyoko.domain.interfaces.llm import LLMClientInterface
from lyoko.domain.interfaces.mcp import MCPClientInterface

logger = logging.getLogger("lyoko.specialists")


class DomainSpecialistAgent:
    """Specialist subagent focused on a single domain (e.g. unifi, kubernetes, homeassistant, grafana)."""

    def __init__(
        self,
        name: str,
        domain: str,
        system_prompt: str,
        llm: LLMClientInterface | None = None,
        mcp_client: MCPClientInterface | None = None,
        tools: list[Any] | None = None,
    ) -> None:
        self.name = name
        self.domain = domain
        self.system_prompt = system_prompt
        self.llm = llm
        self.mcp_client = mcp_client
        self.tools = tools or []

    async def run(
        self,
        prompt: str,
        session_id: str | None = None,
        user_id: str | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Execute a domain specialist query."""
        logger.info("Running specialist %s for query: %s", self.name, prompt)
        if self.llm is None:
            return f"Specialist {self.name}: LLM client not configured."

        specialist_tags = list(tags or [])
        specialist_tags.extend(["specialist", f"specialist:{self.domain}"])

        return await self.llm.chat(
            prompt=prompt,
            system_prompt=self.system_prompt,
            tools=self.tools if self.tools else None,
            session_id=session_id,
            user_id=user_id,
            trace_name=f"specialist-{self.domain}",
            tags=specialist_tags,
            metadata=metadata or {},
        )
