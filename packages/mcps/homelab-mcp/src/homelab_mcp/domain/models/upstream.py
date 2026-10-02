"""Upstream MCP domain models."""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class UpstreamType(StrEnum):
    HOME_ASSISTANT = "homeassistant"
    UNIFI = "unifi"
    KUBERNETES = "kubernetes"
    GRAFANA = "grafana"
    GITHUB = "github"


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    parameters: dict[str, Any] = field(default_factory=dict)
    upstream_type: UpstreamType | str = "unknown"


@dataclass(frozen=True)
class ToolResult:
    status: str
    content: Any
    is_error: bool = False
