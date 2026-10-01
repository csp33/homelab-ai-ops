"""Incident domain exceptions."""

from lyoko.domain.exceptions.base import LyokoError


class IncidentNotFoundError(LyokoError):
    """Raised when a requested incident cannot be located."""


class IncidentRemediationError(LyokoError):
    """Raised when automated incident remediation fails."""
