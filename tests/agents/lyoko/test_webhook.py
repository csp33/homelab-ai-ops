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
    mock_tracer.get_callback_handler.return_value = mock_callback

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
    mock_workflow.ainvoke.assert_called_once()
    _, kwargs = mock_workflow.ainvoke.call_args
    assert "config" in kwargs
    assert kwargs["config"]["callbacks"] == [mock_callback]
    assert "lyoko" in kwargs["config"]["tags"]
