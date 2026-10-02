"""Unit tests for LYOKO agent domain models."""

from lyoko.domain.models import (
    FeedbackRequest,
    Incident,
    IncidentState,
    IncidentStatus,
    MemoryEntry,
    MemoryQueryResult,
)


def test_lyoko_incident_model():
    incident = Incident(
        alert_name="KubePodCrashLooping",
        namespace="media",
        pod_name="radarr-79dfb8bf7-x82k",
        deployment_name="radarr",
    )
    assert incident.namespace == "media"
    assert incident.pod_name == "radarr-79dfb8bf7-x82k"
    assert incident.deployment_name == "radarr"


def test_lyoko_incident_state():
    incident = Incident(
        alert_name="KubePodCrashLooping",
        namespace="media",
        pod_name="radarr-79dfb8bf7-x82k",
        deployment_name="radarr",
    )
    state = IncidentState(
        incident=incident,
        status=IncidentStatus.DIAGNOSING,
        diagnostics={"logs": "Out of memory"},
        action_taken="Bumped limit to 1Gi",
        verification_success=True,
    )
    assert state.incident.deployment_name == "radarr"
    assert state.status == IncidentStatus.DIAGNOSING
    assert state.diagnostics["logs"] == "Out of memory"
    assert state.verification_success is True


def test_lyoko_memory_domain_models():
    entry = MemoryEntry(
        id=10,
        namespace="monitoring",
        service_name="prometheus",
        alert_name="TargetDown",
        incident_pattern="Connection refused",
        operator_feedback="Check DNS before restart",
        action_rule="Verify endpoint",
    )
    assert entry.id == 10
    assert entry.service_name == "prometheus"
    assert entry.operator_feedback == "Check DNS before restart"

    req = FeedbackRequest(
        namespace="monitoring",
        service_name="prometheus",
        incident_pattern="TargetDown Connection refused",
        operator_feedback="Check DNS before restart",
    )
    assert req.service_name == "prometheus"
    assert req.incident_pattern == "TargetDown Connection refused"

    result = MemoryQueryResult(memory=entry, similarity=0.92)
    assert result.similarity == 0.92
    assert result.memory.id == 10
