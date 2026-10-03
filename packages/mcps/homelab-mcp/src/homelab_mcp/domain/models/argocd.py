"""Domain models for Argo CD applications and sync policies."""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ArgoCDAppInfo:
    """Information summary of an Argo CD application."""

    name: str
    namespace: str = "argocd"
    project: str = "default"
    repo_url: str = ""
    path: str = ""
    target_revision: str = "HEAD"
    sync_status: str = "Unknown"
    health_status: str = "Unknown"
    auto_sync_enabled: bool = False
    self_heal_enabled: bool = False
    is_paused: bool = False
    paused_reason: str | None = None
    paused_at: str | None = None
    incident_id: str | None = None
    annotations: dict[str, str] = field(default_factory=dict)
    raw_status: dict[str, Any] = field(default_factory=dict)
