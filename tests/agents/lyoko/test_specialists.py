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
    assert (
        "Grafana" in OBSERVABILITY_SPECIALIST_PROMPT
        or "Prometheus" in OBSERVABILITY_SPECIALIST_PROMPT
    )


@pytest.mark.asyncio
async def test_all_specialists_carry_filtering_discipline():
    for prompt in (
        K8S_SPECIALIST_PROMPT,
        NETWORK_SPECIALIST_PROMPT,
        SMARTHOME_SPECIALIST_PROMPT,
        OBSERVABILITY_SPECIALIST_PROMPT,
    ):
        assert "Filtering discipline" in prompt
        assert "filter the returned output yourself" in prompt


@pytest.mark.asyncio
async def test_domain_specialist_run_executes_with_scoped_domain():
    mock_llm = MagicMock(spec=LLMClientInterface)
    mock_llm.chat = AsyncMock(return_value="Top client: humberto (435 GB)")
    mock_mcp = MagicMock(spec=MCPClientInterface)
    mock_mcp.get_domain_langchain_tools = AsyncMock(return_value=["mock_tool_1", "mock_tool_2"])
    mock_mcp.get_domain_catalog = AsyncMock(
        return_value=[
            {
                "name": "unifi_list_clients",
                "description": "List network clients",
                "parameters": {
                    "type": "object",
                    "properties": {"network": {"type": "string"}, "limit": {"type": "integer"}},
                    "required": ["network"],
                },
            }
        ]
    )

    agent = DomainSpecialistAgent(
        name="NetworkSpecialist",
        domain="unifi",
        system_prompt=NETWORK_SPECIALIST_PROMPT,
        llm=mock_llm,
        mcp_client=mock_mcp,
    )

    tools = await agent.get_tools()
    assert len(tools) == 2
    mock_mcp.get_domain_langchain_tools.assert_awaited_once_with("unifi", authorizer=None)

    response = await agent.run("Top bandwidth consumers", session_id="test-session")
    assert "humberto" in response
    mock_llm.chat.assert_awaited_once()
    call_kwargs = mock_llm.chat.await_args.kwargs
    assert call_kwargs["prompt"] == "Top bandwidth consumers"
    assert call_kwargs["system_prompt"].startswith(NETWORK_SPECIALIST_PROMPT)
    assert "AVAILABLE TOOLS IN YOUR DOMAIN" in call_kwargs["system_prompt"]
    assert "unifi_list_clients(network, limit?)" in call_kwargs["system_prompt"]
    assert "specialist:unifi" in call_kwargs["tags"]
    assert call_kwargs["tools"] == ["mock_tool_1", "mock_tool_2"]
