"""Multi-Agent Supervisor and Cross-Domain Orchestrator for LYOKO."""

import logging
from typing import Any

from lyoko.domain.interfaces.llm import LLMClientInterface

logger = logging.getLogger("lyoko.supervisor")

SUPERVISOR_SYSTEM_PROMPT = """You are the Central Multi-Agent Supervisor for LYOKO.
You coordinate domain specialist subagents across the homelab infrastructure:
- Kubernetes SRE Specialist (`kubernetes`): Pods, deployments, logs, restarts, resource limits.
- UniFi Network Specialist (`unifi`): Network clients, bandwidth consumption, WiFi, switches, ports, VLANs.
- Smart Home Specialist (`homeassistant`): Devices, entities, climate, lighting, integrations.
- Observability Specialist (`grafana`): Prometheus metrics, dashboards, alert histories.

Your primary responsibilities:
1. TRIAGE & INTENT DECOMPOSITION: Analyze user requests. If a request spans multiple domains (e.g. scale a pod in K8s and reload an integration in Home Assistant), decompose it into a logical multi-step plan.
2. SPECIALIST DELEGATION: Delegate domain-specific tasks to the appropriate specialist agent.
3. SYNTHESIS: Consolidate responses from specialists into a cohesive, structured, and clear response for the operator."""


class SupervisorAgent:
    """Orchestrates domain specialist subagents and plans multi-step cross-domain tasks."""

    def __init__(
        self,
        specialists: dict[str, Any] | None = None,
        llm: LLMClientInterface | None = None,
    ) -> None:
        self.specialists = specialists or {}
        self.llm = llm

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
