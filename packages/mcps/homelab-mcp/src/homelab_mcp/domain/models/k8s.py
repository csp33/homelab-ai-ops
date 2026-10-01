"""Kubernetes domain models."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ContainerTerminationInfo:
    reason: str | None = None
    exit_code: int | None = None
    message: str | None = None


@dataclass(frozen=True)
class ContainerInfo:
    name: str
    ready: bool
    restart_count: int
    last_termination: ContainerTerminationInfo | None = None


@dataclass(frozen=True)
class PodDiagnostic:
    name: str
    namespace: str
    phase: str
    node_name: str | None
    containers: list[ContainerInfo] = field(default_factory=list)
    logs_tail: str = ""


@dataclass(frozen=True)
class ResourcePatch:
    memory_limit: str | None = None
    memory_request: str | None = None
    cpu_limit: str | None = None
    cpu_request: str | None = None
