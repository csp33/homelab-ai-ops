"""Unit tests for LYOKO agent domain models."""

from lyoko.domain.models import (
    Incident,
    IncidentState,
    IncidentStatus,
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
