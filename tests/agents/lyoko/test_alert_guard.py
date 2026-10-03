"""Unit tests for LYOKO Alert Storm Protection & Cascade Trace Prevention."""

import asyncio
from unittest.mock import AsyncMock

import pytest
from lyoko.application.alert_guard import AlertStormProtector, CircuitState
from lyoko.config import AgentSettings
from lyoko.domain.models.incident import Incident


@pytest.fixture
def custom_settings() -> AgentSettings:
    return AgentSettings(
        postgres_password="",
        alert_debounce_seconds=0.1,  # Fast for tests
        alert_storm_threshold=3,
        alert_storm_window_seconds=1,
        alert_storm_cooldown_seconds=1,
        alert_dedup_cooldown_seconds=2,
        max_concurrent_incidents=2,
    )


@pytest.mark.asyncio
async def test_debounce_aggregates_multiple_alerts_into_single_incident(
    custom_settings: AgentSettings,
):
    dispatched_incidents: list[Incident] = []

    async def mock_dispatch(incident: Incident) -> None:
        dispatched_incidents.append(incident)

    protector = AlertStormProtector(
        settings=custom_settings,
        dispatch_callback=mock_dispatch,
    )

    alerts = [
        {
            "status": "firing",
            "labels": {"alertname": "KubeNodeNotReady", "namespace": "default", "node": "worker-1"},
            "annotations": {"summary": "Node worker-1 not ready"},
            "fingerprint": "fp-1",
        },
        {
            "status": "firing",
            "labels": {"alertname": "KubePodCrashLooping", "namespace": "default", "pod": "pod-a"},
            "annotations": {"summary": "Pod-a is crashlooping"},
            "fingerprint": "fp-2",
        },
        {
            "status": "firing",
            "labels": {"alertname": "TargetDown", "namespace": "default", "job": "cadvisor"},
            "annotations": {"summary": "Cadvisor target is down"},
            "fingerprint": "fp-3",
        },
    ]

    await protector.ingest_alerts(alerts)
    # Wait for debounce window (0.1s)
    await asyncio.sleep(0.25)

    assert len(dispatched_incidents) == 1
    primary_incident = dispatched_incidents[0]
    assert primary_incident.namespace == "default"
    # Should have correlated alerts
    assert len(primary_incident.correlated_alerts) == 2


@pytest.mark.asyncio
async def test_in_flight_lock_prevents_duplicate_incident(custom_settings: AgentSettings):
    dispatched_incidents: list[Incident] = []

    async def mock_dispatch(incident: Incident) -> None:
        dispatched_incidents.append(incident)

    protector = AlertStormProtector(
        settings=custom_settings,
        dispatch_callback=mock_dispatch,
    )

    alert = {
        "status": "firing",
        "labels": {"alertname": "KubePodCrashLooping", "namespace": "media", "pod": "sonarr-123"},
        "fingerprint": "fp-sonarr",
    }

    # First ingestion
    await protector.ingest_alerts([alert])
    await asyncio.sleep(0.2)
    assert len(dispatched_incidents) == 1

    # While in-flight, second ingestion should be dropped
    await protector.ingest_alerts([alert])
    await asyncio.sleep(0.2)
    assert len(dispatched_incidents) == 1


@pytest.mark.asyncio
async def test_dedup_cooldown_prevents_flapping(custom_settings: AgentSettings):
    dispatched_incidents: list[Incident] = []

    async def mock_dispatch(incident: Incident) -> None:
        dispatched_incidents.append(incident)

    protector = AlertStormProtector(
        settings=custom_settings,
        dispatch_callback=mock_dispatch,
    )

    alert = {
        "status": "firing",
        "labels": {"alertname": "KubePodCrashLooping", "namespace": "media", "pod": "radarr-123"},
        "fingerprint": "fp-radarr",
    }

    await protector.ingest_alerts([alert])
    await asyncio.sleep(0.2)
    assert len(dispatched_incidents) == 1

    # Mark completed (which puts it into cooldown)
    key = protector.get_incident_key(dispatched_incidents[0])
    protector.mark_completed(key)

    # Immediately ingest same alert again
    await protector.ingest_alerts([alert])
    await asyncio.sleep(0.2)
    # Should still only be 1 because it's in cooldown
    assert len(dispatched_incidents) == 1


@pytest.mark.asyncio
async def test_circuit_breaker_trips_on_alert_storm(custom_settings: AgentSettings):
    mock_chat_manager = AsyncMock()
    dispatched_incidents: list[Incident] = []

    async def mock_dispatch(incident: Incident) -> None:
        dispatched_incidents.append(incident)

    protector = AlertStormProtector(
        settings=custom_settings,  # threshold is 3
        chat_manager=mock_chat_manager,
        dispatch_callback=mock_dispatch,
    )

    # Ingest 5 different alerts quickly
    alerts = [
        {
            "status": "firing",
            "labels": {"alertname": f"Alert{i}", "namespace": f"ns-{i}"},
            "fingerprint": f"fp-{i}",
        }
        for i in range(5)
    ]

    await protector.ingest_alerts(alerts)
    await asyncio.sleep(0.2)

    assert protector.circuit_state == CircuitState.OPEN
    # Chat manager should receive warning notification with approval button or broadcast
    assert (
        mock_chat_manager.broadcast_approval_request.called
        or mock_chat_manager.broadcast_message.called
        or mock_chat_manager.send_message.called
    )


@pytest.mark.asyncio
async def test_force_approval_dispatches_suppressed_incident(custom_settings: AgentSettings):
    from lyoko.domain.models.chat import ApprovalResponse

    mock_chat = AsyncMock()
    dispatched_incidents: list[Incident] = []

    async def mock_dispatch(incident: Incident) -> None:
        dispatched_incidents.append(incident)

    protector = AlertStormProtector(
        settings=custom_settings,
        chat_manager=mock_chat,
        dispatch_callback=mock_dispatch,
    )

    alert = {
        "status": "firing",
        "labels": {"alertname": "KubePodCrashLooping", "namespace": "media", "pod": "sonarr-123"},
        "fingerprint": "fp-sonarr-123",
    }

    # 1. First dispatch
    await protector.ingest_alerts([alert])
    await asyncio.sleep(0.2)
    assert len(dispatched_incidents) == 1
    key = protector.get_incident_key(dispatched_incidents[0])
    protector.mark_completed(key)

    # 2. Ingest while in cooldown (should be suppressed, but saved so operator can force it)
    await protector.ingest_alerts([alert])
    await asyncio.sleep(0.2)
    assert len(dispatched_incidents) == 1
    assert mock_chat.broadcast_approval_request.called

    # 3. Operator clicks "Procesar de todas formas"
    resp = ApprovalResponse(incident_id=key, approved=True, user_id="12345", action_id="force")
    handled = await protector.handle_force_approval(resp)
    assert handled is True
    await asyncio.sleep(0.2)

    # Now it must be dispatched!
    assert len(dispatched_incidents) == 2
    assert dispatched_incidents[1].pod_name == "sonarr-123"
