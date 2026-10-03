"""Unit tests for DomainSpecialistAgent and specialized prompts."""

from unittest.mock import AsyncMock, MagicMock
import pytest

from lyoko.application.specialists.agent import DomainSpecialistAgent
from lyoko.application.specialists.prompts import (
    K8S_SPECIALIST_PROMPT,
    NETWORK_SPECIALIST_PROMPT,
    OBSERVABILITY_SPECIALIST_PROMPT,
    SMARTHOME_SPECIALIST_PROMPT,
)
from lyoko.domain.interfaces.llm import LLMClientInterface
from lyoko.domain.interfaces.mcp import MCPClientInterface


@pytest.mark.asyncio
async def test_domain_specialist_initialization_and_prompts():
    assert "Kubernetes" in K8S_SPECIALIST_PROMPT
    assert "UniFi" in NETWORK_SPECIALIST_PROMPT
    assert "Home Assistant" in SMARTHOME_SPECIALIST_PROMPT
    assert "Grafana" in OBSERVABILITY_SPECIALIST_PROMPT or "Prometheus" in OBSERVABILITY_SPECIALIST_PROMPT


@pytest.mark.asyncio
async def test_domain_specialist_run_executes_with_scoped_domain():
    mock_llm = MagicMock(spec=LLMClientInterface)
    mock_llm.chat = AsyncMock(return_value="Top client: humberto (435 GB)")
    mock_mcp = MagicMock(spec=MCPClientInterface)

    agent = DomainSpecialistAgent(
        name="NetworkSpecialist",
        domain="unifi",
        system_prompt=NETWORK_SPECIALIST_PROMPT,
        llm=mock_llm,
        mcp_client=mock_mcp,
    )

    response = await agent.run("Top bandwidth consumers", session_id="test-session")
    assert "humberto" in response
    mock_llm.chat.assert_awaited_once()
    call_kwargs = mock_llm.chat.await_args.kwargs
    assert call_kwargs["prompt"] == "Top bandwidth consumers"
    assert call_kwargs["system_prompt"] == NETWORK_SPECIALIST_PROMPT
    assert "specialist:unifi" in call_kwargs["tags"]
