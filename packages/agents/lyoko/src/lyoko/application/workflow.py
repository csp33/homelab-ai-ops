"""LangGraph StateGraph of LYOKO: one graph, two branches.

Every event enters at ``route`` and takes one of two branches::

    START -> route -+-> chat                                      -> END
                    +-> diagnose -> remediate -> verify -> notify -> END

* ``chat`` answers an operator message, or carries out a request, in a single tool-using run.
* The incident branch investigates, fixes, verifies and reports. Alertmanager alerts always
  take it. A Telegram message takes it when the router decides the operator is reporting
  something broken, and takes ``chat`` otherwise.

The agent runs use the sector5-mcp gateway through domain specialists. The supervisor
delegates to Kubernetes, UniFi, Home Assistant, and Grafana specialists so each phase
operates with a scoped toolset instead of searching the whole catalog.

Safety does not rely on the agent's judgement. Every run gets a ``ToolGate`` built from one
policy for both branches: read-only tools run, auto-approved tools run, and everything else waits
for the operator. Diagnosis and verification are stricter still and cannot change anything.

Every agent run receives the node's run config, so one event produces one trace in which each
node and each agent run is a named child span.
"""

from collections.abc import Sequence
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from lyoko.application.chat_manager import ChatManager
from lyoko.application.hitl import ApprovalManager
from lyoko.application.nodes.incident_remediate import create_remediate_node
from lyoko.application.nodes.incident_verify import create_verify_node
from lyoko.application.nodes.notify import create_notify_node
from lyoko.application.nodes.router import choose_branch, create_route_node
from lyoko.application.nodes.triage import create_composite_triage_node
from lyoko.application.triage.base import TriageHandler
from lyoko.application.triage.dispatcher import choose_triage
from lyoko.config import settings  # noqa: F401
from lyoko.domain.interfaces.embeddings import EmbeddingsServiceInterface
from lyoko.domain.interfaces.llm import LLMClientInterface
from lyoko.domain.interfaces.memory import MemoryRepositoryInterface
from lyoko.domain.models.incident import CoordinatorNext, SpecialistDomain


class LyokoState(TypedDict, total=False):
    # What happened. ``event_type`` is "alert" (the default) or "message".
    event_type: str
    event_id: str
    """Short id of this run. It prefixes approval ids, which end up in Telegram callback data."""
    session_id: str
    """Observability session the run belongs to (a chat session, or the incident)."""
    chat_id: str
    message_thread_id: str | None
    """Telegram forum topic / thread of the originating message, for threaded replies."""
    text: str
    """The operator's message, for ``event_type == "message"``."""
    history_context: str
    """Recent conversation context injected into the chat prompt for short-term memory."""
    alert_name: str
    labels: dict[str, str]
    annotations: dict[str, str]

    # Routing and chat branch
    route: str
    reply: str
    """The text to send back to the operator, set by ``chat`` and, for messages, by ``notify``."""

    # Incident branch
    root_cause: str
    plan: str
    action_taken: str
    actions: list[dict[str, Any]]
    verification: str
    is_resolved: bool
    requires_escalation: bool
    matched_memories: list[dict[str, Any]]
    lessons_context: str
    correlated_alerts: list[dict[str, Any]]
    progress_message_id: str | None
    progress_chat_id: str | None
    """Reference to the live status message that is edited as the incident advances."""


def create_lyoko_graph(
    mcp_client: Any,
    approval_manager: ApprovalManager | None = None,
    chat_manager: ChatManager | None = None,
    checkpointer: Any = None,
    llm: LLMClientInterface | None = None,
    supervisor: Any = None,
    specialists: dict[str, Any] | None = None,
    memory_repository: MemoryRepositoryInterface | None = None,
    embeddings_service: EmbeddingsServiceInterface | None = None,
    diagnose_llm: LLMClientInterface | None = None,
    diagnose_supervisor: Any = None,
    tracer: Any = None,
    triage_handlers: Sequence[TriageHandler] | None = None,
) -> Any:
    """Build the LangGraph StateGraph that routes, answers, investigates and remediates.

    ``diagnose_llm``/``diagnose_supervisor`` optionally give the diagnose phase a different model
    than the rest of the graph; both fall back to ``llm``/``supervisor`` when omitted.
    """
    route_node = create_route_node(llm=llm)
    if triage_handlers is not None:
        handlers = triage_handlers
    else:
        from lyoko.composition import build_triage_handlers

        handlers = build_triage_handlers(
            mcp_client=mcp_client,
            approval_manager=approval_manager,
            chat_manager=chat_manager,
            tracer=tracer,
        )
    triage_node = create_composite_triage_node(handlers=handlers)

    from lyoko.application.nodes.coordinator import (
        choose_coordinator_next,
        create_coordinator_node,
    )
    from lyoko.application.nodes.specialists import create_specialist_node

    coordinator_node = create_coordinator_node(
        mcp_client=mcp_client,
        llm=llm,
        supervisor=supervisor,
        approval_manager=approval_manager,
        chat_manager=chat_manager,
        memory_repository=memory_repository,
        embeddings_service=embeddings_service,
        diagnose_llm=diagnose_llm,
        diagnose_supervisor=diagnose_supervisor,
    )
    remediate_node = create_remediate_node(
        mcp_client=mcp_client,
        llm=llm,
        supervisor=supervisor,
        approval_manager=approval_manager,
        chat_manager=chat_manager,
    )
    verify_node = create_verify_node(
        mcp_client=mcp_client,
        llm=llm,
        supervisor=supervisor,
        approval_manager=approval_manager,
        chat_manager=chat_manager,
    )
    notify_node = create_notify_node(chat_manager=chat_manager)

    workflow = StateGraph(LyokoState)
    workflow.add_node("route", route_node)
    workflow.add_node("triage", triage_node)
    workflow.add_node("coordinator", coordinator_node)

    # Specialist nodes
    specialists_dict = specialists or {}
    for domain in SpecialistDomain:
        spec = specialists_dict.get(domain.value)
        node_fn = create_specialist_node(
            domain=domain.value,
            specialist=spec,
            mcp_client=mcp_client,
            approval_manager=approval_manager,
            chat_manager=chat_manager,
        )
        workflow.add_node(domain.value, node_fn)
        workflow.add_edge(domain.value, "coordinator")

    workflow.add_node("remediate", remediate_node)
    workflow.add_node("verify", verify_node)
    workflow.add_node("notify", notify_node)

    workflow.add_edge(START, "route")
    workflow.add_conditional_edges(
        "route",
        choose_branch,
        {"chat": "coordinator", "diagnose": "triage"},
    )
    workflow.add_conditional_edges(
        "triage",
        choose_triage,
        {"handled": "notify", "diagnose": "coordinator"},
    )
    workflow.add_conditional_edges(
        "coordinator",
        choose_coordinator_next,
        {
            CoordinatorNext.KUBERNETES.value: SpecialistDomain.KUBERNETES.value,
            CoordinatorNext.UNIFI.value: SpecialistDomain.UNIFI.value,
            CoordinatorNext.HOMEASSISTANT.value: SpecialistDomain.HOMEASSISTANT.value,
            CoordinatorNext.GRAFANA.value: SpecialistDomain.GRAFANA.value,
            CoordinatorNext.REMEDIATE.value: "remediate",
            CoordinatorNext.CHAT_END.value: END,
        },
    )
    workflow.add_edge("remediate", "verify")
    workflow.add_edge("verify", "notify")
    workflow.add_edge("notify", END)

    return workflow.compile(checkpointer=checkpointer)


# Backward compatibility alias for tests and external callers
create_remediation_workflow = create_lyoko_graph
