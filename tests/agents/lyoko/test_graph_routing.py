"""Routing and the two branches of the LYOKO graph: chat and incident."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.callbacks import BaseCallbackHandler
from lyoko.application.hitl import ApprovalManager
from lyoko.application.workflow import create_lyoko_graph
from lyoko.domain.interfaces.mcp import ToolAuthorizer

from tests.agents.lyoko.fakes import (
    DIAGNOSIS_ACTIONABLE,
    FakeMCPClient,
    Operator,
    ScriptedLLM,
)

SCALE_ARGS = {"name": "sonarr", "namespace": "media", "replicas": 2}


@pytest.fixture(autouse=True)
def _settings(monkeypatch):
    monkeypatch.setattr("lyoko.application.workflow.settings.verification_delay_seconds", 0)
    monkeypatch.setattr("lyoko.application.workflow.settings.auto_approved_tools", [])


def _message(text: str = "scale sonarr to 2 replicas", thread_id: str | None = None) -> dict:
    return {
        "event_type": "message",
        "event_id": "chat-ab12cd34",
        "session_id": "telegram-42-1760000000",
        "chat_id": "42",
        "message_thread_id": thread_id,
        "text": text,
        "labels": {},
        "annotations": {},
    }


def _alert() -> dict:
    return {
        "event_type": "alert",
        "event_id": "incident-abc",
        "session_id": "incident-abc",
        "alert_name": "KubePodCrashLooping",
        "labels": {"alertname": "KubePodCrashLooping", "namespace": "media"},
        "annotations": {},
    }


def _scale(outcomes: list):
    async def chat(authorize: ToolAuthorizer) -> str:
        refusal = await authorize("resources_scale", SCALE_ARGS)
        outcomes.append(refusal)
        return "Scaled sonarr to 2." if refusal is None else "I could not scale it."

    return chat


# ----------------------------------------------------------------------
# Routing
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_alert_goes_straight_to_the_incident_branch_without_asking_the_router():
    llm = ScriptedLLM(
        diagnose="ROOT_CAUSE: x\nACTIONABLE: no\nPLAN: y",
        route="CHAT",
    )
    graph = create_lyoko_graph(mcp_client=FakeMCPClient(), llm=llm)

    await graph.ainvoke(_alert())

    assert llm.calls == ["diagnose"]


@pytest.mark.asyncio
async def test_alert_without_an_event_type_is_still_an_alert():
    """States written before the router existed carry no event_type."""
    state = _alert()
    del state["event_type"]
    llm = ScriptedLLM(diagnose="ROOT_CAUSE: x\nACTIONABLE: no\nPLAN: y")
    graph = create_lyoko_graph(mcp_client=FakeMCPClient(), llm=llm)

    await graph.ainvoke(state)

    assert llm.calls == ["diagnose"]


@pytest.mark.asyncio
async def test_message_the_router_calls_chat_is_answered_in_one_run():
    llm = ScriptedLLM(route="CHAT", chat="Your printer is at 192.168.1.50.")
    graph = create_lyoko_graph(mcp_client=FakeMCPClient(), llm=llm)

    result = await graph.ainvoke(_message("what IP does the printer have?"))

    assert result["reply"] == "Your printer is at 192.168.1.50."
    assert llm.calls == ["route", "chat"]
    assert llm.prompts["route"] == "what IP does the printer have?"
    assert llm.prompts["chat"] == "what IP does the printer have?"


@pytest.mark.asyncio
async def test_message_the_router_calls_an_incident_runs_the_incident_branch():
    llm = ScriptedLLM(
        route="INCIDENT",
        diagnose="ROOT_CAUSE: The database credentials are invalid.\nACTIONABLE: no\nPLAN: rotate",
    )
    chat = AsyncMock()
    graph = create_lyoko_graph(mcp_client=FakeMCPClient(), chat_manager=chat, llm=llm)

    result = await graph.ainvoke(_message("sonarr keeps crashing, fix it"))

    assert llm.calls == ["route", "diagnose"]
    assert "sonarr keeps crashing, fix it" in llm.prompts["diagnose"]
    assert "Incident Report" in result["reply"]
    assert "sonarr keeps crashing, fix it" in result["reply"]
    assert "database credentials" in result["reply"]
    # The Telegram handler replies with the report. Broadcasting it too would send it twice.
    chat.broadcast_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_alert_report_is_broadcast_and_not_returned_as_a_reply():
    llm = ScriptedLLM(diagnose="ROOT_CAUSE: x\nACTIONABLE: no\nPLAN: y")
    chat = AsyncMock()
    graph = create_lyoko_graph(mcp_client=FakeMCPClient(), chat_manager=chat, llm=llm)

    result = await graph.ainvoke(_alert())

    chat.broadcast_message.assert_awaited_once()
    assert "reply" not in result


@pytest.mark.parametrize("answer", ["", "maybe?", "Not sure, honestly."])
@pytest.mark.asyncio
async def test_unclear_router_answer_falls_back_to_chat(answer):
    llm = ScriptedLLM(route=answer, chat="ok")
    graph = create_lyoko_graph(mcp_client=FakeMCPClient(), llm=llm)

    result = await graph.ainvoke(_message())

    assert result["reply"] == "ok"
    assert llm.calls == ["route", "chat"]


@pytest.mark.asyncio
async def test_router_failure_falls_back_to_chat():
    async def broken(_: ToolAuthorizer) -> str:
        raise RuntimeError("router model unavailable")

    class FailingRouter(ScriptedLLM):
        async def chat(self, *args, **kwargs):
            if "phase:route" in (kwargs.get("tags") or []):
                raise RuntimeError("router model unavailable")
            return await super().chat(*args, **kwargs)

    llm = FailingRouter(chat="answered anyway")
    graph = create_lyoko_graph(mcp_client=FakeMCPClient(), llm=llm)

    result = await graph.ainvoke(_message())

    assert result["reply"] == "answered anyway"


@pytest.mark.asyncio
async def test_message_without_llm_says_so():
    graph = create_lyoko_graph(mcp_client=FakeMCPClient(), llm=None)

    result = await graph.ainvoke(_message("ping"))

    assert "LLM provider not configured" in result["reply"]
    assert "ping" in result["reply"]


@pytest.mark.asyncio
async def test_chat_failure_is_reported_as_the_reply():
    class Failing(ScriptedLLM):
        async def chat(self, *args, **kwargs):
            if "phase:chat" in (kwargs.get("tags") or []):
                raise RuntimeError("OpenAI API rate limit exceeded")
            return await super().chat(*args, **kwargs)

    graph = create_lyoko_graph(mcp_client=FakeMCPClient(), llm=Failing(route="CHAT"))

    result = await graph.ainvoke(_message())

    assert "⚠️ Error processing your question:" in result["reply"]
    assert "OpenAI API rate limit exceeded" in result["reply"]


# ----------------------------------------------------------------------
# Approval gate in chat
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_change_waits_for_approval_then_runs():
    manager = ApprovalManager()
    operator = Operator(manager, approve=True)
    chat = AsyncMock()
    chat.broadcast_approval_request = operator.broadcast_approval_request
    outcomes: list = []
    llm = ScriptedLLM(route="CHAT", chat=_scale(outcomes))
    graph = create_lyoko_graph(
        mcp_client=FakeMCPClient(), approval_manager=manager, chat_manager=chat, llm=llm
    )

    result = await graph.ainvoke(_message())

    assert outcomes == [None]
    assert result["reply"] == "Scaled sonarr to 2."
    assert [a["outcome"] for a in result["actions"]] == ["approved"]
    (request,) = operator.requests
    assert "resources_scale" in request.details
    assert "Chat request: scale sonarr to 2 replicas" in request.details
    assert '"replicas": 2' in request.details


@pytest.mark.asyncio
async def test_chat_approval_belongs_to_the_chat_session_and_fits_telegram_limits():
    manager = ApprovalManager()
    operator = Operator(manager, approve=True)
    chat = AsyncMock()
    chat.broadcast_approval_request = operator.broadcast_approval_request
    llm = ScriptedLLM(route="CHAT", chat=_scale([]))
    graph = create_lyoko_graph(
        mcp_client=FakeMCPClient(), approval_manager=manager, chat_manager=chat, llm=llm
    )

    await graph.ainvoke(_message())

    (request,) = operator.requests
    # Replying to the approval message continues the chat session, not a made-up one.
    assert request.session_id == "telegram-42-1760000000"
    assert request.incident_id == "chat-ab12cd34.1"
    assert request.chat_id == "42"
    assert len(f"approve:{request.incident_id}".encode()) <= 64


@pytest.mark.asyncio
async def test_chat_approval_is_sent_into_the_message_thread():
    manager = ApprovalManager()
    operator = Operator(manager, approve=True)
    chat = AsyncMock()
    chat.broadcast_approval_request = operator.broadcast_approval_request
    llm = ScriptedLLM(route="CHAT", chat=_scale([]))
    graph = create_lyoko_graph(
        mcp_client=FakeMCPClient(), approval_manager=manager, chat_manager=chat, llm=llm
    )

    await graph.ainvoke(_message(thread_id="321"))

    assert operator.thread_ids == ["321"]


@pytest.mark.asyncio
async def test_chat_change_denied_does_not_run():
    manager = ApprovalManager()
    operator = Operator(manager, approve=False, reason="not now")
    chat = AsyncMock()
    chat.broadcast_approval_request = operator.broadcast_approval_request
    outcomes: list = []
    llm = ScriptedLLM(route="CHAT", chat=_scale(outcomes))
    graph = create_lyoko_graph(
        mcp_client=FakeMCPClient(), approval_manager=manager, chat_manager=chat, llm=llm
    )

    result = await graph.ainvoke(_message())

    assert outcomes[0] is not None and "did not approve" in outcomes[0]
    assert [a["outcome"] for a in result["actions"]] == ["denied"]


@pytest.mark.asyncio
async def test_chat_runs_trusted_tools_without_asking(monkeypatch):
    monkeypatch.setattr(
        "lyoko.application.workflow.settings.auto_approved_tools", ["resources_scale"]
    )
    manager = ApprovalManager()
    operator = Operator(manager, approve=False)
    chat = AsyncMock()
    chat.broadcast_approval_request = operator.broadcast_approval_request
    outcomes: list = []
    llm = ScriptedLLM(route="CHAT", chat=_scale(outcomes))
    graph = create_lyoko_graph(
        mcp_client=FakeMCPClient(), approval_manager=manager, chat_manager=chat, llm=llm
    )

    result = await graph.ainvoke(_message())

    assert outcomes == [None]
    assert operator.requests == []
    assert [a["outcome"] for a in result["actions"]] == ["auto_approved"]


@pytest.mark.asyncio
async def test_chat_reads_never_ask():
    manager = ApprovalManager()
    operator = Operator(manager, approve=False)
    chat = AsyncMock()
    chat.broadcast_approval_request = operator.broadcast_approval_request
    seen: list = []

    async def read(authorize: ToolAuthorizer) -> str:
        seen.append(await authorize("pods_get", {"name": "x"}))
        seen.append(await authorize("resources_list", {"kind": "Pod"}))
        return "listed"

    llm = ScriptedLLM(route="CHAT", chat=read)
    graph = create_lyoko_graph(
        mcp_client=FakeMCPClient(), approval_manager=manager, chat_manager=chat, llm=llm
    )

    result = await graph.ainvoke(_message())

    assert seen == [None, None]
    assert operator.requests == []
    assert result["actions"] == []


@pytest.mark.asyncio
async def test_chat_change_is_refused_when_there_is_no_approval_channel():
    outcomes: list = []
    llm = ScriptedLLM(route="CHAT", chat=_scale(outcomes))
    graph = create_lyoko_graph(mcp_client=FakeMCPClient(), llm=llm)

    result = await graph.ainvoke(_message())

    assert outcomes[0] is not None and "no approval channel" in outcomes[0]
    assert [a["outcome"] for a in result["actions"]] == ["refused"]


@pytest.mark.asyncio
async def test_approval_in_chat_does_not_block_another_event():
    """A chat run waiting for the operator must not stop an alert from being handled."""
    import asyncio

    manager = ApprovalManager()
    chat = AsyncMock()
    requests: list = []

    async def broadcast(request, message_thread_id=None) -> None:
        requests.append(request)

    chat.broadcast_approval_request = broadcast
    chat_llm = ScriptedLLM(route="CHAT", chat=_scale([]))
    alert_llm = ScriptedLLM(diagnose="ROOT_CAUSE: x\nACTIONABLE: no\nPLAN: y")
    chat_graph = create_lyoko_graph(
        mcp_client=FakeMCPClient(), approval_manager=manager, chat_manager=chat, llm=chat_llm
    )
    alert_graph = create_lyoko_graph(mcp_client=FakeMCPClient(), llm=alert_llm)

    waiting = asyncio.create_task(chat_graph.ainvoke(_message()))
    await asyncio.sleep(0.05)
    assert not waiting.done()

    await alert_graph.ainvoke(_alert())
    assert not waiting.done()

    from lyoko.domain.models.chat import ApprovalResponse

    manager.resolve_approval(
        ApprovalResponse(incident_id=requests[0].incident_id, approved=True, user_id="admin")
    )
    result = await asyncio.wait_for(waiting, timeout=2)
    assert result["reply"] == "Scaled sonarr to 2."


# ----------------------------------------------------------------------
# Tracing
# ----------------------------------------------------------------------


class _Recorder(BaseCallbackHandler):
    def __init__(self) -> None:
        self.chain_names: list[str] = []

    def on_chain_start(self, serialized, inputs, *, name=None, **kwargs):
        self.chain_names.append(name or "")


@pytest.mark.asyncio
async def test_every_agent_call_receives_the_run_config_of_its_node():
    """Agent runs are children of the graph run, so one event makes one trace."""
    recorder = _Recorder()
    llm = ScriptedLLM(route="CHAT", chat="ok")
    graph = create_lyoko_graph(mcp_client=FakeMCPClient(), llm=llm)

    await graph.ainvoke(_message(), config={"callbacks": [recorder]})

    for phase in ("route", "chat"):
        parent = llm.parent_configs[phase]
        assert parent is not None, phase
        assert parent.get("callbacks"), phase


@pytest.mark.asyncio
async def test_incident_phases_receive_the_run_config_too():
    llm = ScriptedLLM(
        diagnose=DIAGNOSIS_ACTIONABLE,
        remediate="RESULT: nothing to do",
    )
    graph = create_lyoko_graph(mcp_client=FakeMCPClient(), llm=llm)

    await graph.ainvoke(_alert(), config={"callbacks": [_Recorder()]})

    for phase in ("diagnose", "remediate"):
        assert llm.parent_configs[phase] is not None, phase
        assert llm.parent_configs[phase].get("callbacks"), phase


@pytest.mark.asyncio
async def test_graph_nodes_are_named_after_the_phase():
    recorder = _Recorder()
    llm = ScriptedLLM(route="CHAT", chat="ok")
    graph = create_lyoko_graph(mcp_client=FakeMCPClient(), llm=llm)

    await graph.ainvoke(_message(), config={"callbacks": [recorder]})

    assert "route" in recorder.chain_names
    assert "chat" in recorder.chain_names


@pytest.mark.asyncio
async def test_chat_branch_uses_supervisor_when_provided():
    mock_supervisor = MagicMock()
    mock_supervisor.coordinate = AsyncMock(return_value="Supervisor handled request.")

    workflow = create_lyoko_graph(
        mcp_client=FakeMCPClient(),
        llm=ScriptedLLM(route="CHAT"),
        supervisor=mock_supervisor,
    )

    result = await workflow.ainvoke(_message("what is the status of the network?"))
    assert result["reply"] == "Supervisor handled request."
    mock_supervisor.coordinate.assert_awaited_once()
    kwargs = mock_supervisor.coordinate.await_args.kwargs
    assert kwargs["prompt"] == "what is the status of the network?"
    assert kwargs["authorizer"] is not None
    assert "phase:chat" in kwargs["tags"]
    assert kwargs.get("tools") is None


@pytest.mark.asyncio
async def test_diagnose_uses_supervisor_when_provided():
    mock_supervisor = MagicMock()
    mock_supervisor.coordinate = AsyncMock(
        return_value=(
            "ROOT_CAUSE: Application gambling-song-staging is OutOfSync.\n"
            "ACTIONABLE: no\n"
            "PLAN: Ask a human to inspect the Argo CD sync diff."
        )
    )

    workflow = create_lyoko_graph(
        mcp_client=FakeMCPClient(),
        llm=ScriptedLLM(),
        supervisor=mock_supervisor,
    )

    result = await workflow.ainvoke(
        {
            "event_id": "incident-abc",
            "alert_name": "ArgoCDAppOutOfSync",
            "labels": {"alertname": "ArgoCDAppOutOfSync", "name": "gambling-song-staging"},
            "annotations": {"summary": "OutOfSync"},
        }
    )

    assert "OutOfSync" in result["root_cause"]
    assert result["requires_escalation"] is True
    mock_supervisor.coordinate.assert_awaited_once()
    kwargs = mock_supervisor.coordinate.await_args.kwargs
    assert "phase:diagnose" in kwargs["tags"]
    assert kwargs["authorizer"] is not None
    assert "ArgoCDAppOutOfSync" in kwargs["prompt"]
