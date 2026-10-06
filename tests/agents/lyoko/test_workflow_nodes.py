"""Unit tests for isolated LYOKO workflow nodes and helper functions."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from lyoko.application.nodes.helpers import (
    format_pairs,
    incident_context,
    is_message,
    origin,
    truncate,
)
from lyoko.application.nodes.notify import format_incident_report
from lyoko.application.nodes.router import choose_branch, create_route_node
from lyoko.domain.interfaces.llm import LLMClientInterface


def test_workflow_node_helpers():
    pairs = {"a": "1", "b": "2"}
    formatted = format_pairs(pairs)
    assert "- a: 1" in formatted
    assert "- b: 2" in formatted

    empty_formatted = format_pairs({})
    assert empty_formatted == "- (none)"

    msg_state = {"event_type": "message", "text": "restart router"}
    assert is_message(msg_state) is True
    assert "Problem reported" in incident_context(msg_state)
    assert "Chat request: restart router" in origin(msg_state)

    alert_state = {"event_type": "alert", "alert_name": "HighMemory"}
    assert is_message(alert_state) is False
    assert "Alert: HighMemory" in incident_context(alert_state)
    assert "Alert: HighMemory" in origin(alert_state)

    long_text = "word " * 100
    assert len(truncate(long_text)) <= 205


def test_format_incident_report():
    state = {
        "is_resolved": True,
        "alert_name": "CrashLoopBackOff",
        "labels": {"namespace": "media", "pod": "sonarr-0"},
        "root_cause": "Disk full",
        "action_taken": "Cleaned up temp logs",
        "actions": [{"tool": "cleanup_disk", "outcome": "auto_approved"}],
        "verification": "Pod running 0 restarts",
    }
    report = format_incident_report(state)
    assert "STATUS:* RESOLVED" in report or "Status:* RESOLVED" in report
    assert "CrashLoopBackOff" in report
    assert "Disk full" in report
    assert "Cleaned up temp logs" in report


@pytest.mark.asyncio
async def test_route_node_and_choose_branch():
    assert choose_branch({"route": "incident"}) == "diagnose"
    assert choose_branch({"route": "chat"}) == "chat"

    # Alert always routes to incident without calling LLM
    route_node_no_llm = create_route_node(llm=None)
    res_alert = await route_node_no_llm({"event_type": "alert"}, MagicMock())
    assert res_alert["route"] == "incident"

    # Message with no LLM defaults to chat
    res_msg = await route_node_no_llm({"event_type": "message", "text": "hello"}, MagicMock())
    assert res_msg["route"] == "chat"

    # Message with LLM
    mock_llm = MagicMock(spec=LLMClientInterface)
    mock_llm.chat = AsyncMock(return_value="INCIDENT")
    route_node_llm = create_route_node(llm=mock_llm)
    res_routed = await route_node_llm({"event_type": "message", "text": "pod crashed"}, MagicMock())
    assert res_routed["route"] == "incident"


def test_status_callback_reads_only_config_configurable():
    from lyoko.application.nodes.helpers import status_callback

    sentinel = object()
    assert status_callback({"configurable": {"on_status": sentinel}}) is sentinel
    assert status_callback({"configurable": {}}) is None
    assert status_callback(None) is None
    assert status_callback("not-a-config") is None


@pytest.mark.asyncio
async def test_diagnose_node_forwards_streaming_status_callback(monkeypatch):
    """The incident branch must forward on_status so the placeholder shows steps, not 'Thinking…'."""
    import lyoko.application.nodes.incident_diagnose as diagnose_module

    captured: dict[str, object] = {}

    async def fake_run_supervised(*args, **kwargs):  # noqa: ANN002, ANN003
        captured.update(kwargs)
        return "ROOT_CAUSE: drift\nACTIONABLE: no\nPLAN: check"

    monkeypatch.setattr(diagnose_module, "run_supervised", fake_run_supervised)

    node = diagnose_module.create_diagnose_node(mcp_client=object(), llm=object())
    sentinel = object()
    state = {"event_type": "message", "text": "hi", "event_id": "evt-1", "session_id": "s1"}
    await node(state, {"configurable": {"on_status": sentinel}})

    assert captured.get("on_status") is sentinel
