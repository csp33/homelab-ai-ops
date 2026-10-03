"""Domain interface for Argo CD operations."""

from abc import ABC, abstractmethod
from typing import Any

from homelab_mcp.domain.models.argocd import ArgoCDAppInfo


class ArgoCDClientInterface(ABC):
    """Port interface defining operations on Argo CD applications."""

    @abstractmethod
    async def get_application(self, app_name: str, namespace: str = "argocd") -> ArgoCDAppInfo:
        """Retrieve details and sync/health status of an Argo CD application."""

    @abstractmethod
    async def list_applications(self, namespace: str = "argocd") -> list[ArgoCDAppInfo]:
        """List all Argo CD applications in the given namespace."""

    @abstractmethod
    async def pause_application(
        self,
        app_name: str,
        reason: str,
        incident_id: str | None = None,
        namespace: str = "argocd",
    ) -> dict[str, Any]:
        """Temporarily pause self-healing and auto-sync on an Argo CD application."""

    @abstractmethod
    async def resume_application(
        self,
        app_name: str,
        namespace: str = "argocd",
    ) -> dict[str, Any]:
        """Resume original auto-sync and self-healing policy on an Argo CD application."""

    @abstractmethod
    async def sync_application(
        self,
        app_name: str,
        prune: bool = False,
        namespace: str = "argocd",
    ) -> dict[str, Any]:
        """Trigger an immediate sync or refresh on an Argo CD application."""
