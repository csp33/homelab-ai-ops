"""Unit tests for SupervisorAgent multi-agent coordination."""

from unittest.mock import AsyncMock, MagicMock
import pytest

from lyoko.application.supervisor import SUPERVISOR_SYSTEM_PROMPT, SupervisorAgent
from lyoko.domain.interfaces.llm import LLMClientInterface


@pytest.mark.asyncio
async def test_supervisor_initialization():
    assert "Supervisor" in SUPERVISOR_SYSTEM_PROMPT
    assert "specialist" in SUPERVISOR_SYSTEM_PROMPT.lower()


@pytest.mark.asyncio
async def test_supervisor_coordinates_multi_step():
    mock_k8s = AsyncMock(return_value="Pod memory updated to 512Mi")
    mock_ha = AsyncMock(return_value="Zigbee integration reloaded successfully")

    mock_llm = MagicMock(spec=LLMClientInterface)
    mock_llm.chat = AsyncMock(
        return_value="All actions completed: Pod scaled to 512Mi and Zigbee integration reloaded."
    )

    supervisor = SupervisorAgent(
        specialists={
            "kubernetes": mock_k8s,
            "homeassistant": mock_ha,
        },
        llm=mock_llm,
    )

    result = await supervisor.coordinate(
        prompt="Scale pod zigbee2mqtt memory and reload zigbee in HA",
        session_id="test-session",
    )
    assert "completed" in result.lower()
    mock_llm.chat.assert_awaited_once()
