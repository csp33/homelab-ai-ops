"""Unit tests for LYOKO FastAPI Alertmanager webhook receiver."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from lyoko.infrastructure.web.controller import create_webhook_router


@pytest.fixture
def mock_workflow():
    workflow = MagicMock()
    workflow.ainvoke = AsyncMock()
    return workflow


@pytest.fixture
def test_client(mock_workflow):
    app = FastAPI()
    router = create_webhook_router(mock_workflow)
    app.include_router(router)
    return TestClient(app)


def test_alertmanager_webhook_firing_alert(test_client, mock_workflow):
    payload = {
        "status": "firing",
        "alerts": [
            {
                "status": "firing",
                "labels": {
                    "alertname": "KubePodCrashLooping",
                    "namespace": "media",
                    "pod": "radarr-79dfb8bf7-x82k",
                    "deployment": "radarr",
                },
                "annotations": {
                    "summary": "Pod radarr is crashlooping",
                },
                "fingerprint": "abc12345",
            }
        ],
    }

    response = test_client.post("/webhook/alertmanager", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "accepted"
    assert "Processing 1 alerts" in data["message"]
    mock_workflow.ainvoke.assert_called_once()
    _, kwargs = mock_workflow.ainvoke.call_args
    config = kwargs.get("config", {})
    assert config.get("configurable") == {"thread_id": "incident-abc12345"}
    assert "lyoko" in config.get("tags", [])
    assert config.get("metadata", {}).get("pod_name") == "radarr-79dfb8bf7-x82k"


def test_alertmanager_webhook_ignored_resolved(test_client, mock_workflow):
    payload = {
        "status": "resolved",
        "alerts": [
            {
                "status": "resolved",
                "labels": {
                    "alertname": "KubePodCrashLooping",
                    "namespace": "media",
                    "pod": "radarr-xxx",
                },
            }
        ],
    }

    response = test_client.post("/webhook/alertmanager", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "accepted"


def test_alertmanager_webhook_invalid_json(test_client):
    response = test_client.post(
        "/webhook/alertmanager",
        content="not-json",
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 400


def test_alertmanager_webhook_with_tracer(mock_workflow):
    mock_tracer = MagicMock()
    mock_callback = MagicMock()
    mock_tracer.get_trace_config.return_value = {
        "callbacks": [mock_callback],
        "tags": ["lyoko", "ns:default", "alert:OOMKilled"],
        "metadata": {"langfuse_session_id": "incident-api-123"},
        "run_name": "lyoko-OOMKilled-api-123",
    }

    app = FastAPI()
    router = create_webhook_router(mock_workflow, tracer=mock_tracer)
    app.include_router(router)
    client = TestClient(app)

    payload = {
        "status": "firing",
        "alerts": [
            {
                "status": "firing",
                "labels": {
                    "alertname": "OOMKilled",
                    "namespace": "default",
                    "pod": "api-123",
                },
            }
        ],
    }

    response = client.post("/webhook/alertmanager", json=payload)
    assert response.status_code == 200
    mock_tracer.get_trace_config.assert_called_once_with(
        session_id="incident-api-123",
        user_id="alert:OOMKilled",
        trace_name="lyoko-OOMKilled-api-123",
        tags=["lyoko", "ns:default", "alert:OOMKilled"],
        metadata={
            "namespace": "default",
            "pod_name": "api-123",
            "alert_name": "OOMKilled",
            "fingerprint": "",
        },
    )
    mock_workflow.ainvoke.assert_called_once()
    _, kwargs = mock_workflow.ainvoke.call_args
    assert "config" in kwargs
    assert kwargs["config"]["callbacks"] == [mock_callback]
    assert kwargs["config"]["metadata"]["langfuse_session_id"] == "incident-api-123"
