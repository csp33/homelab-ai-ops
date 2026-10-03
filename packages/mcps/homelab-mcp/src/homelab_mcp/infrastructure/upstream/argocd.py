"""Argo CD Custom Resource upstream adapter for Kubernetes."""

import asyncio
import json
import logging
from datetime import UTC, datetime
from typing import Any

from homelab_mcp.domain.exceptions.argocd import (
    ArgoCDAppNotFoundError,
    ArgoCDOperationError,
)
from homelab_mcp.domain.interfaces.argocd import ArgoCDClientInterface
from homelab_mcp.domain.interfaces.upstream import UpstreamMCPInterface
from homelab_mcp.domain.models.argocd import ArgoCDAppInfo
from homelab_mcp.domain.models.upstream import ToolDefinition, ToolResult, UpstreamType
from kubernetes import client, config
from kubernetes.client.exceptions import ApiException

logger = logging.getLogger("homelab_mcp.upstream.argocd")

GROUP = "argoproj.io"
VERSION = "v1alpha1"
PLURAL = "applications"


class ArgoCDUpstreamClient(ArgoCDClientInterface, UpstreamMCPInterface):
    """Interacts with Argo CD Application CRDs via Kubernetes CustomObjectsApi."""

    def __init__(
        self,
        custom_objects_api: Any | None = None,
        kubeconfig_path: str | None = None,
        default_namespace: str = "argocd",
    ) -> None:
        self.default_namespace = default_namespace
        self._custom_api = custom_objects_api
        self._kubeconfig_path = kubeconfig_path
        self._initialized = custom_objects_api is not None

    def _get_api(self) -> Any:
        """Lazy-initialize Kubernetes CustomObjectsApi."""
        if self._custom_api is not None:
            return self._custom_api

        if not self._initialized:
            try:
                if self._kubeconfig_path:
                    config.load_kube_config(config_file=self._kubeconfig_path)
                else:
                    try:
                        config.load_incluster_config()
                    except Exception:
                        config.load_kube_config()
                self._custom_api = client.CustomObjectsApi()
                self._initialized = True
            except Exception as exc:
                logger.error(f"Failed to initialize Kubernetes CustomObjectsApi: {exc}")
                raise ArgoCDOperationError(
                    f"Kubernetes client initialization failed: {exc}"
                ) from exc

        return self._custom_api

    def _parse_app_info(self, item: dict[str, Any]) -> ArgoCDAppInfo:
        metadata = item.get("metadata", {})
        spec = item.get("spec", {})
        status = item.get("status", {})
        annotations = metadata.get("annotations", {}) or {}

        sync_policy = spec.get("syncPolicy", {}) or {}
        automated = sync_policy.get("automated") if isinstance(sync_policy, dict) else None
        has_automated = automated is not None
        self_heal = bool(automated.get("selfHeal", False)) if isinstance(automated, dict) else False

        sync_status = status.get("sync", {}).get("status", "Unknown")
        health_status = status.get("health", {}).get("status", "Unknown")

        source = spec.get("source", {}) or {}

        return ArgoCDAppInfo(
            name=metadata.get("name", "unknown"),
            namespace=metadata.get("namespace", self.default_namespace),
            project=spec.get("project", "default"),
            repo_url=source.get("repoURL", ""),
            path=source.get("path", ""),
            target_revision=source.get("targetRevision", "HEAD"),
            sync_status=sync_status,
            health_status=health_status,
            auto_sync_enabled=has_automated,
            self_heal_enabled=self_heal,
            is_paused=annotations.get("lyoko.homelab/maintenance") == "active",
            paused_reason=annotations.get("lyoko.homelab/paused-reason"),
            paused_at=annotations.get("lyoko.homelab/paused-at"),
            incident_id=annotations.get("lyoko.homelab/incident-id"),
            annotations=annotations,
            raw_status=status,
        )

    async def get_application(self, app_name: str, namespace: str = "argocd") -> ArgoCDAppInfo:
        ns = namespace or self.default_namespace
        api = self._get_api()
        loop = asyncio.get_running_loop()
        try:
            item = await loop.run_in_executor(
                None,
                lambda: api.get_namespaced_custom_object(
                    group=GROUP,
                    version=VERSION,
                    namespace=ns,
                    plural=PLURAL,
                    name=app_name,
                ),
            )
            return self._parse_app_info(item)
        except ApiException as exc:
            if exc.status == 404:
                raise ArgoCDAppNotFoundError(
                    f"Argo CD application '{app_name}' not found in namespace '{ns}'."
                ) from exc
            raise ArgoCDOperationError(
                f"Failed to get Argo CD application '{app_name}': {exc.reason} (HTTP {exc.status})"
            ) from exc
        except Exception as exc:
            if isinstance(exc, (ArgoCDAppNotFoundError, ArgoCDOperationError)):
                raise
            raise ArgoCDOperationError(
                f"Unexpected error getting Argo CD application '{app_name}': {exc}"
            ) from exc

    async def list_applications(self, namespace: str = "argocd") -> list[ArgoCDAppInfo]:
        ns = namespace or self.default_namespace
        api = self._get_api()
        loop = asyncio.get_running_loop()
        try:
            result = await loop.run_in_executor(
                None,
                lambda: api.list_namespaced_custom_object(
                    group=GROUP,
                    version=VERSION,
                    namespace=ns,
                    plural=PLURAL,
                ),
            )
            items = result.get("items", [])
            return [self._parse_app_info(item) for item in items]
        except Exception as exc:
            raise ArgoCDOperationError(f"Failed to list Argo CD applications: {exc}") from exc

    async def pause_application(
        self,
        app_name: str,
        reason: str,
        incident_id: str | None = None,
        namespace: str = "argocd",
    ) -> dict[str, Any]:
        ns = namespace or self.default_namespace
        api = self._get_api()
        loop = asyncio.get_running_loop()

        try:
            # 1. Fetch current object
            current = await loop.run_in_executor(
                None,
                lambda: api.get_namespaced_custom_object(
                    group=GROUP,
                    version=VERSION,
                    namespace=ns,
                    plural=PLURAL,
                    name=app_name,
                ),
            )
        except ApiException as exc:
            if exc.status == 404:
                raise ArgoCDAppNotFoundError(
                    f"Argo CD application '{app_name}' not found in namespace '{ns}'."
                ) from exc
            raise ArgoCDOperationError(f"Failed to fetch '{app_name}' for pausing: {exc}") from exc

        spec = current.get("spec", {})
        sync_policy = spec.get("syncPolicy")
        metadata = current.get("metadata", {})
        existing_annotations = metadata.get("annotations", {}) or {}

        # If already paused, do not overwrite the original sync policy
        original_policy_str = existing_annotations.get("lyoko.homelab/original-sync-policy")
        if original_policy_str is None and sync_policy is not None:
            original_policy_str = json.dumps(sync_policy)
        elif original_policy_str is None:
            original_policy_str = json.dumps({})

        patch_annotations = {
            "lyoko.homelab/maintenance": "active",
            "lyoko.homelab/paused-reason": reason,
            "lyoko.homelab/paused-at": datetime.now(UTC).isoformat(),
            "lyoko.homelab/original-sync-policy": original_policy_str,
        }
        if incident_id:
            patch_annotations["lyoko.homelab/incident-id"] = incident_id

        # Merge patch to disable automated sync
        patch_body = {
            "metadata": {
                "annotations": patch_annotations,
            },
            "spec": {
                "syncPolicy": None,
            },
        }

        try:
            await loop.run_in_executor(
                None,
                lambda: api.patch_namespaced_custom_object(
                    group=GROUP,
                    version=VERSION,
                    namespace=ns,
                    plural=PLURAL,
                    name=app_name,
                    body=patch_body,
                ),
            )
            logger.info(f"Argo CD application '{app_name}' paused successfully (reason: {reason}).")
            return {
                "status": "success",
                "app_name": app_name,
                "action": "paused",
                "reason": reason,
                "incident_id": incident_id,
                "saved_sync_policy": original_policy_str,
            }
        except Exception as exc:
            raise ArgoCDOperationError(
                f"Failed to patch Argo CD application '{app_name}' to paused: {exc}"
            ) from exc

    async def resume_application(
        self,
        app_name: str,
        namespace: str = "argocd",
    ) -> dict[str, Any]:
        ns = namespace or self.default_namespace
        api = self._get_api()
        loop = asyncio.get_running_loop()

        try:
            current = await loop.run_in_executor(
                None,
                lambda: api.get_namespaced_custom_object(
                    group=GROUP,
                    version=VERSION,
                    namespace=ns,
                    plural=PLURAL,
                    name=app_name,
                ),
            )
        except ApiException as exc:
            if exc.status == 404:
                raise ArgoCDAppNotFoundError(
                    f"Argo CD application '{app_name}' not found in namespace '{ns}'."
                ) from exc
            raise ArgoCDOperationError(
                f"Failed to fetch '{app_name}' for resumption: {exc}"
            ) from exc

        metadata = current.get("metadata", {})
        existing_annotations = metadata.get("annotations", {}) or {}
        saved_policy_str = existing_annotations.get("lyoko.homelab/original-sync-policy")

        restored_sync_policy = None
        if saved_policy_str:
            try:
                restored_sync_policy = json.loads(saved_policy_str)
            except Exception as exc:
                logger.warning(
                    f"Failed to parse saved sync policy JSON '{saved_policy_str}': {exc}"
                )
                restored_sync_policy = {"automated": {"selfHeal": True, "prune": True}}

        # Clear maintenance annotations by setting to None
        patch_annotations = {
            "lyoko.homelab/maintenance": None,
            "lyoko.homelab/paused-reason": None,
            "lyoko.homelab/paused-at": None,
            "lyoko.homelab/original-sync-policy": None,
            "lyoko.homelab/incident-id": None,
        }

        patch_body = {
            "metadata": {
                "annotations": patch_annotations,
            },
            "spec": {
                "syncPolicy": restored_sync_policy,
            },
        }

        try:
            await loop.run_in_executor(
                None,
                lambda: api.patch_namespaced_custom_object(
                    group=GROUP,
                    version=VERSION,
                    namespace=ns,
                    plural=PLURAL,
                    name=app_name,
                    body=patch_body,
                ),
            )
            logger.info(f"Argo CD application '{app_name}' resumed successfully.")
            return {
                "status": "success",
                "app_name": app_name,
                "action": "resumed",
                "restored_sync_policy": restored_sync_policy,
            }
        except Exception as exc:
            raise ArgoCDOperationError(
                f"Failed to resume Argo CD application '{app_name}': {exc}"
            ) from exc

    async def sync_application(
        self,
        app_name: str,
        prune: bool = False,
        namespace: str = "argocd",
    ) -> dict[str, Any]:
        ns = namespace or self.default_namespace
        api = self._get_api()
        loop = asyncio.get_running_loop()

        # Setting argocd.argoproj.io/refresh: "hard" triggers a forced refresh
        # Adding operation.sync triggers an immediate sync
        patch_body = {
            "metadata": {
                "annotations": {
                    "argocd.argoproj.io/refresh": "hard",
                }
            },
            "operation": {
                "sync": {
                    "prune": prune,
                    "syncStrategy": {
                        "hook": {},
                    },
                },
                "initiatedBy": {
                    "username": "lyoko-agent",
                },
            },
        }

        try:
            await loop.run_in_executor(
                None,
                lambda: api.patch_namespaced_custom_object(
                    group=GROUP,
                    version=VERSION,
                    namespace=ns,
                    plural=PLURAL,
                    name=app_name,
                    body=patch_body,
                ),
            )
            logger.info(f"Argo CD application '{app_name}' sync/refresh initiated.")
            return {
                "status": "success",
                "app_name": app_name,
                "action": "sync_initiated",
                "prune": prune,
            }
        except Exception as exc:
            raise ArgoCDOperationError(
                f"Failed to trigger sync on Argo CD application '{app_name}': {exc}"
            ) from exc

    # UpstreamMCPInterface implementation
    async def list_tools(self) -> list[ToolDefinition]:
        return [
            ToolDefinition(
                name="argocd_pause_app",
                description=(
                    "Temporarily pause Argo CD auto-sync and self-healing for an application during incident remediation. "
                    "Prevents GitOps controllers from overwriting emergency live Kubernetes patches."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "app_name": {
                            "type": "string",
                            "description": "Name of the Argo CD application (e.g. 'immich', 'nextcloud', 'vaultwarden').",
                        },
                        "reason": {
                            "type": "string",
                            "description": "Reason for pausing self-heal (e.g. 'OOMKilled memory bump 512Mi -> 1Gi').",
                        },
                        "incident_id": {
                            "type": "string",
                            "description": "Optional incident ID or tracking ticket.",
                        },
                        "namespace": {
                            "type": "string",
                            "description": "Argo CD namespace (default: 'argocd').",
                            "default": "argocd",
                        },
                    },
                    "required": ["app_name", "reason"],
                },
                upstream_type=UpstreamType.KUBERNETES,
            ),
            ToolDefinition(
                name="argocd_resume_app",
                description=(
                    "Resume Argo CD auto-sync and self-healing for an application after hotfix PR has been merged to Git. "
                    "Restores the saved original sync policy and removes maintenance annotations."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "app_name": {
                            "type": "string",
                            "description": "Name of the Argo CD application to resume.",
                        },
                        "namespace": {
                            "type": "string",
                            "description": "Argo CD namespace (default: 'argocd').",
                            "default": "argocd",
                        },
                    },
                    "required": ["app_name"],
                },
                upstream_type=UpstreamType.KUBERNETES,
            ),
            ToolDefinition(
                name="argocd_sync_app",
                description=(
                    "Trigger an immediate refresh and sync operation on an Argo CD application without waiting for polling interval."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "app_name": {
                            "type": "string",
                            "description": "Name of the Argo CD application to synchronize.",
                        },
                        "prune": {
                            "type": "boolean",
                            "description": "Whether to prune orphaned resources (default: false).",
                            "default": False,
                        },
                        "namespace": {
                            "type": "string",
                            "description": "Argo CD namespace (default: 'argocd').",
                            "default": "argocd",
                        },
                    },
                    "required": ["app_name"],
                },
                upstream_type=UpstreamType.KUBERNETES,
            ),
            ToolDefinition(
                name="argocd_get_app",
                description=(
                    "Get full status, health, sync state, and maintenance annotations of an Argo CD application."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "app_name": {
                            "type": "string",
                            "description": "Name of the Argo CD application to inspect.",
                        },
                        "namespace": {
                            "type": "string",
                            "description": "Argo CD namespace (default: 'argocd').",
                            "default": "argocd",
                        },
                    },
                    "required": ["app_name"],
                },
                upstream_type=UpstreamType.KUBERNETES,
            ),
            ToolDefinition(
                name="argocd_list_apps",
                description="List all Argo CD applications and their sync/health statuses.",
                parameters={
                    "type": "object",
                    "properties": {
                        "namespace": {
                            "type": "string",
                            "description": "Argo CD namespace (default: 'argocd').",
                            "default": "argocd",
                        },
                    },
                },
                upstream_type=UpstreamType.KUBERNETES,
            ),
        ]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        try:
            if name == "argocd_pause_app":
                res = await self.pause_application(
                    app_name=arguments["app_name"],
                    reason=arguments.get("reason", "Incident remediation"),
                    incident_id=arguments.get("incident_id"),
                    namespace=arguments.get("namespace", self.default_namespace),
                )
                return ToolResult(status="success", content=res)
            elif name == "argocd_resume_app":
                res = await self.resume_application(
                    app_name=arguments["app_name"],
                    namespace=arguments.get("namespace", self.default_namespace),
                )
                return ToolResult(status="success", content=res)
            elif name == "argocd_sync_app":
                res = await self.sync_application(
                    app_name=arguments["app_name"],
                    prune=arguments.get("prune", False),
                    namespace=arguments.get("namespace", self.default_namespace),
                )
                return ToolResult(status="success", content=res)
            elif name == "argocd_get_app":
                info = await self.get_application(
                    app_name=arguments["app_name"],
                    namespace=arguments.get("namespace", self.default_namespace),
                )
                return ToolResult(
                    status="success",
                    content={
                        "name": info.name,
                        "namespace": info.namespace,
                        "project": info.project,
                        "repo_url": info.repo_url,
                        "path": info.path,
                        "target_revision": info.target_revision,
                        "sync_status": info.sync_status,
                        "health_status": info.health_status,
                        "auto_sync_enabled": info.auto_sync_enabled,
                        "self_heal_enabled": info.self_heal_enabled,
                        "is_paused": info.is_paused,
                        "paused_reason": info.paused_reason,
                        "paused_at": info.paused_at,
                        "incident_id": info.incident_id,
                    },
                )
            elif name == "argocd_list_apps":
                apps = await self.list_applications(
                    namespace=arguments.get("namespace", self.default_namespace)
                )
                return ToolResult(
                    status="success",
                    content=[
                        {
                            "name": a.name,
                            "namespace": a.namespace,
                            "sync_status": a.sync_status,
                            "health_status": a.health_status,
                            "auto_sync_enabled": a.auto_sync_enabled,
                            "is_paused": a.is_paused,
                            "paused_reason": a.paused_reason,
                        }
                        for a in apps
                    ],
                )
            else:
                return ToolResult(
                    status="error", content=f"Unknown Argo CD tool '{name}'", is_error=True
                )
        except Exception as exc:
            logger.error(f"Error executing Argo CD tool '{name}': {exc}")
            return ToolResult(status="error", content=str(exc), is_error=True)
