"""Unit and integration tests for Argo CD upstream client in homelab-mcp."""

import json
from unittest.mock import MagicMock

import pytest
from homelab_mcp.domain.exceptions.argocd import (
    ArgoCDAppNotFoundError,
)
from homelab_mcp.infrastructure.upstream.argocd import ArgoCDUpstreamClient
from kubernetes.client.exceptions import ApiException


@pytest.fixture
def mock_custom_api():
    return MagicMock()


@pytest.fixture
def sample_app_manifest():
    return {
        "metadata": {
            "name": "immich",
            "namespace": "argocd",
            "annotations": {
                "some-existing-annotation": "value",
            },
        },
        "spec": {
            "project": "default",
            "source": {
                "repoURL": "https://github.com/csp33/k8s-at-home-charts",
                "path": "charts/immich",
                "targetRevision": "main",
            },
            "syncPolicy": {
                "automated": {
                    "prune": True,
                    "selfHeal": True,
                },
                "syncOptions": ["CreateNamespace=true"],
            },
        },
        "status": {
            "sync": {
                "status": "Synced",
            },
            "health": {
                "status": "Healthy",
            },
        },
    }


@pytest.mark.asyncio
async def test_argocd_get_application(mock_custom_api, sample_app_manifest):
    mock_custom_api.get_namespaced_custom_object.return_value = sample_app_manifest
    client = ArgoCDUpstreamClient(custom_objects_api=mock_custom_api)

    app_info = await client.get_application("immich")
    assert app_info.name == "immich"
    assert app_info.sync_status == "Synced"
    assert app_info.health_status == "Healthy"
    assert app_info.auto_sync_enabled is True
    assert app_info.self_heal_enabled is True
    assert app_info.is_paused is False


@pytest.mark.asyncio
async def test_argocd_get_application_not_found(mock_custom_api):
    mock_custom_api.get_namespaced_custom_object.side_effect = ApiException(
        status=404, reason="Not Found"
    )
    client = ArgoCDUpstreamClient(custom_objects_api=mock_custom_api)

    with pytest.raises(ArgoCDAppNotFoundError):
        await client.get_application("nonexistent-app")


@pytest.mark.asyncio
async def test_argocd_pause_application(mock_custom_api, sample_app_manifest):
    mock_custom_api.get_namespaced_custom_object.return_value = sample_app_manifest
    mock_custom_api.patch_namespaced_custom_object.return_value = {}
    client = ArgoCDUpstreamClient(custom_objects_api=mock_custom_api)

    result = await client.pause_application(
        app_name="immich",
        reason="OOMKilled memory bump 512Mi -> 1Gi",
        incident_id="INC-1234",
    )

    assert result["status"] == "success"
    assert result["action"] == "paused"
    assert result["incident_id"] == "INC-1234"

    # Verify patch body sent to K8s API
    _, kwargs = mock_custom_api.patch_namespaced_custom_object.call_args
    patch_body = kwargs["body"]
    assert patch_body["spec"]["syncPolicy"] is None
    annotations = patch_body["metadata"]["annotations"]
    assert annotations["lyoko.homelab/maintenance"] == "active"
    assert annotations["lyoko.homelab/paused-reason"] == "OOMKilled memory bump 512Mi -> 1Gi"
    assert annotations["lyoko.homelab/incident-id"] == "INC-1234"
    assert "prune" in annotations["lyoko.homelab/original-sync-policy"]


@pytest.mark.asyncio
async def test_argocd_resume_application(mock_custom_api, sample_app_manifest):
    # Simulate an application currently paused with saved sync policy
    paused_app = {
        "metadata": {
            "name": "immich",
            "namespace": "argocd",
            "annotations": {
                "lyoko.homelab/maintenance": "active",
                "lyoko.homelab/paused-reason": "Memory bump",
                "lyoko.homelab/original-sync-policy": json.dumps(
                    {"automated": {"prune": True, "selfHeal": True}}
                ),
            },
        },
        "spec": {
            "syncPolicy": None,
        },
    }
    mock_custom_api.get_namespaced_custom_object.return_value = paused_app
    mock_custom_api.patch_namespaced_custom_object.return_value = {}
    client = ArgoCDUpstreamClient(custom_objects_api=mock_custom_api)

    result = await client.resume_application("immich")
    assert result["status"] == "success"
    assert result["action"] == "resumed"

    _, kwargs = mock_custom_api.patch_namespaced_custom_object.call_args
    patch_body = kwargs["body"]
    assert patch_body["spec"]["syncPolicy"] == {"automated": {"prune": True, "selfHeal": True}}
    annotations = patch_body["metadata"]["annotations"]
    assert annotations["lyoko.homelab/maintenance"] is None
    assert annotations["lyoko.homelab/paused-reason"] is None


@pytest.mark.asyncio
async def test_argocd_sync_application(mock_custom_api):
    mock_custom_api.patch_namespaced_custom_object.return_value = {}
    client = ArgoCDUpstreamClient(custom_objects_api=mock_custom_api)

    result = await client.sync_application("immich", prune=True)
    assert result["status"] == "success"
    assert result["action"] == "sync_initiated"

    _, kwargs = mock_custom_api.patch_namespaced_custom_object.call_args
    patch_body = kwargs["body"]
    assert patch_body["metadata"]["annotations"]["argocd.argoproj.io/refresh"] == "hard"
    assert patch_body["operation"]["sync"]["prune"] is True


@pytest.mark.asyncio
async def test_argocd_upstream_tools_discovery_and_dispatch(mock_custom_api, sample_app_manifest):
    mock_custom_api.get_namespaced_custom_object.return_value = sample_app_manifest
    mock_custom_api.patch_namespaced_custom_object.return_value = {}
    client = ArgoCDUpstreamClient(custom_objects_api=mock_custom_api)

    tools = await client.list_tools()
    tool_names = [t.name for t in tools]
    assert "argocd_pause_app" in tool_names
    assert "argocd_resume_app" in tool_names
    assert "argocd_sync_app" in tool_names
    assert "argocd_get_app" in tool_names
    assert "argocd_list_apps" in tool_names

    # Test call_tool dispatch for pause
    pause_res = await client.call_tool(
        "argocd_pause_app",
        {"app_name": "immich", "reason": "Incident #99"},
    )
    assert pause_res.status == "success"
    assert not pause_res.is_error
    assert pause_res.content["action"] == "paused"
