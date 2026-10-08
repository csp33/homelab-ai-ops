"""Unit tests for DomainSpecialistAgent and specialized prompts."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from lyoko.application.agents.specialist_prompts import SpecialistPromptProvider
from lyoko.application.agents.specialists import DomainSpecialistAgent
from lyoko.domain.interfaces.llm import LLMClientInterface
from lyoko.domain.interfaces.mcp import MCPClientInterface


@pytest.mark.asyncio
async def test_domain_specialist_initialization_and_prompts():
    assert "Kubernetes" in SpecialistPromptProvider.get_prompt("k8s")
    assert "UniFi" in SpecialistPromptProvider.get_prompt("network")
    assert "Home Assistant" in SpecialistPromptProvider.get_prompt("smarthome")
    obs_prompt = SpecialistPromptProvider.get_prompt("observability")
    assert "Grafana" in obs_prompt or "Prometheus" in obs_prompt


@pytest.mark.asyncio
async def test_all_specialists_carry_filtering_discipline():
    for domain in ("k8s", "network", "smarthome", "observability"):
        prompt = SpecialistPromptProvider.get_prompt(domain)
        assert "Filtering discipline" in prompt
        assert "filter the returned output yourself" in prompt


@pytest.mark.asyncio
async def test_network_specialist_knows_essid_is_the_wifi_field():
    prompt = SpecialistPromptProvider.get_prompt("network")
    assert "essid" in prompt
    assert "not `ssid`" in prompt


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

    network_prompt = SpecialistPromptProvider.get_prompt("network")
    agent = DomainSpecialistAgent(
        name="NetworkSpecialist",
        domain="unifi",
        system_prompt=network_prompt,
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
    assert call_kwargs["system_prompt"].startswith(network_prompt)
    assert "AVAILABLE TOOLS IN YOUR DOMAIN" in call_kwargs["system_prompt"]
    assert "unifi_list_clients(network, limit?)" in call_kwargs["system_prompt"]
    assert "specialist:unifi" in call_kwargs["tags"]
    assert call_kwargs["tools"] == ["mock_tool_1", "mock_tool_2"]
