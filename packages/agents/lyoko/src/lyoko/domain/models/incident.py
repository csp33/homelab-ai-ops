"""Incident domain models for LYOKO."""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class IncidentStatus(StrEnum):
    PENDING = "pending"
    DIAGNOSING = "diagnosing"
    REMEDIATING = "remediating"
    VERIFYING = "verifying"
    RESOLVED = "resolved"
    ESCALATED = "escalated"
    FAILED = "failed"


@dataclass(frozen=True)
class Incident:
    alert_name: str
    namespace: str
    pod_name: str
    deployment_name: str | None = None
    fingerprint: str | None = None
    labels: dict[str, str] = field(default_factory=dict)


@dataclass
class IncidentState:
    incident: Incident
    status: IncidentStatus = IncidentStatus.PENDING
    diagnostics: dict[str, Any] = field(default_factory=dict)
    root_cause: str | None = None
    action_taken: str | None = None
    verification_success: bool = False
    error_message: str | None = None
    retry_count: int = 0
