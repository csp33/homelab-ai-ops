"""Guardrail and security policy domain exceptions."""

from homelab_mcp.domain.exceptions.base import GatewayError


class GuardrailViolationError(GatewayError):
    """Raised when an operation violates security boundaries or protected namespaces."""
